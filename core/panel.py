"""
This module keeps one control message ("panel") per server in the channel set for that server.

The panel shows whether the server is offline or online, with a Start button while it is offline and Stop and Restart
buttons while it is online (only usable while nobody is online). It is posted once and then only edited, also across
restarts of the bot, and clicks are answered without a new message in the channel (errors only as ephemeral replies).
If other messages may stay in the channel, the panel can be posted again below them, so it is always the newest one.
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

import discord

from core import config as cfg
from core.address import display_address
from core.constants import control_role_id, panel_channels, panel_mode
from core.embeds import COLOR_OFFLINE, COLOR_ONLINE, COLOR_UNKNOWN, MAX_FIELD_LENGTH, new_embed, player_text
from core.server import get_server_stats, get_servers

# Footer text used to find panel messages again, followed by the server ID
PANEL_FOOTER = 'Crafty server panel'
STATE_PATH = os.path.join(os.path.dirname(cfg.CONFIG_PATH), 'panel_state.json')

COLOR_PENDING = discord.Color.gold()

# how long a start or stop may take before the panel shows the real state again
PENDING_TIMEOUT = 300

START = 'start'
STOP = 'stop'
RESTART = 'restart'

# panel.mode: what happens with other messages in a panel channel
DELETE = 'delete'
BOTTOM = 'bottom'
KEEP = 'keep'

# wait this long after a message before posting the panel below it again, so a burst of messages moves it once
REPOST_DELAY = 5

BUTTONS = {
    START: ('Start', '▶️', discord.ButtonStyle.success),
    STOP: ('Stop', '⏹️', discord.ButtonStyle.danger),
    RESTART: ('Restart', '🔄', discord.ButtonStyle.primary),
}

# reply(text) sends an ephemeral answer to the user who clicked, progress(text) shows a step in the panel
Reply = Callable[[str], Awaitable[None]]
Progress = Callable[[str], Awaitable[None]]
# start(server, user mention, reply, progress) and stop/restart(server_id, user mention, reply) -> True if it worked
StartAction = Callable[[dict, str, Reply, Progress], Awaitable[bool]]
StopAction = Callable[[str, str, Reply], Awaitable[bool]]


@dataclass
class Pending:
    """A start, stop or restart in progress, shown until the server is seen in its new state."""
    text: str
    action: str
    until: float
    # restart: when the server was started before, and whether it was seen stopped since
    started: object = None
    seen_down: bool = False


class PanelButton(discord.ui.DynamicItem[discord.ui.Button],
                  template=r'panel:(?P<action>start|stop|restart):(?P<server_id>[0-9a-fA-F-]{36})'):
    """
    The Start, Stop or Restart button of a panel. The action and server are in the custom ID, so the button keeps working
    after a restart of the bot.
    """

    # set by PanelBoard
    board: 'PanelBoard | None' = None

    def __init__(self, action: str, server_id: str, disabled: bool = False):
        label, emoji, style = BUTTONS[action]
        super().__init__(discord.ui.Button(
            style=style,
            label=label,
            emoji=emoji,
            custom_id=f'panel:{action}:{server_id}',
            disabled=disabled,
        ))
        self.action = action
        self.server_id = server_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match):
        return cls(match['action'], match['server_id'])

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.board is None:
            await interaction.response.send_message('The bot is not ready yet, try again in a moment',
                                                    ephemeral=True)
            return
        await self.board.click(interaction, self.action, self.server_id)


class PanelBoard:
    """
    Posts the panel of every server with its own channel and edits it when the server changes.

    Args:
        bot: The Discord bot.
        auto_stop_eta: Function that returns when auto stop will stop a server if nobody joins, or None.
        start: Coroutine function that starts a server, see StartAction.
        stop: Coroutine function that stops a server, see StopAction.
        restart: Coroutine function that restarts a server, see StopAction.
    """

    def __init__(self, bot: discord.Client, auto_stop_eta, start: StartAction, stop: StopAction,
                 restart: StopAction):
        self.bot = bot
        self.auto_stop_eta = auto_stop_eta
        self.start_action = start
        self.stop_action = stop
        self.restart_action = restart
        # server ID -> (channel ID, message ID) of the panel, stored so a restart edits the same message
        self.state: dict[str, list[int]] = self._load()
        self.messages: dict[str, discord.Message] = {}
        # what each panel shows now, so it is only edited when something changed
        self.shown: dict[str, tuple] = {}
        self.pending: dict[str, Pending] = {}
        # servers whose panel is posted again below the other messages on the next update
        self.repost: set[str] = set()
        # channel ID -> waiting task that moves the panels below new messages
        self.repost_tasks: dict[int, asyncio.Task] = {}
        # channel ID -> last message ID already checked for messages below the panels
        self.checked: dict[int, int] = {}
        # servers with a click being handled, so two clicks do not start a server twice
        self.busy: set[str] = set()
        self.lock = asyncio.Lock()
        self.warned_delete = False
        # the last reported setup, so the log only shows changes and not every update
        self.reported: tuple | None = None
        PanelButton.board = self

    # ---- stored message IDs

    @staticmethod
    def _load() -> dict[str, list[int]]:
        try:
            with open(STATE_PATH, encoding='utf-8') as file:
                data = json.load(file)
            return {str(key): [int(value[0]), int(value[1])] for key, value in data.items()}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, TypeError, IndexError) as e:
            print(f'panel: could not read {STATE_PATH}: {e}')
            return {}

    def _save(self) -> None:
        try:
            tmp_path = STATE_PATH + '.tmp'
            with open(tmp_path, 'w', encoding='utf-8') as file:
                json.dump(self.state, file, indent=2)
            os.replace(tmp_path, STATE_PATH)
        except OSError as e:
            print(f'panel: could not write {STATE_PATH}: {e}')

    # ---- content

    def _pending(self, server_id: str, stats: dict | None) -> Pending | None:
        """
        The start, stop or restart in progress, or None. Ends once the server is seen in the new state.
        """
        entry = self.pending.get(server_id)
        if entry is None:
            return None
        running = None if stats is None else bool(stats.get('running'))
        if entry.action == START:
            done = running is True
        elif entry.action == STOP:
            done = running is False
        else:
            if running is False:
                entry.seen_down = True
            # up again: seen stopped in between, or started at another time than before
            done = running is True and (entry.seen_down or stats.get('started') != entry.started)
        # a click still being handled (e.g. a long backup before the start) keeps it
        if done or (time.time() > entry.until and server_id not in self.busy):
            self.pending.pop(server_id, None)
            return None
        return entry

    def _content(self, server: dict, stats: dict | None) -> tuple[discord.Embed, discord.ui.View]:
        server_id = server['server_id']
        name = server.get('server_name', server_id)
        pending = self._pending(server_id, stats)
        running = bool(stats and stats.get('running'))

        if pending is not None:
            embed = new_embed(title=name, description=f'⏳ {pending.text}', color=COLOR_PENDING)
            actions = [START] if pending.action == START else [STOP, RESTART]
            buttons = [PanelButton(action, server_id, disabled=True) for action in actions]
        elif stats is None:
            embed = new_embed(title=name, description='⚪ Unknown, Crafty is not reachable', color=COLOR_UNKNOWN)
            buttons = [PanelButton(START, server_id, disabled=True)]
        elif running:
            embed = new_embed(title=name, description='🟢 Online', color=COLOR_ONLINE)
            online = bool(stats.get('online', 0))
            buttons = [PanelButton(STOP, server_id, disabled=online), PanelButton(RESTART, server_id, disabled=online)]
        else:
            description = '💥 Crashed, press Start to start it again' if stats.get('crashed') else '🔴 Offline'
            embed = new_embed(title=name, description=description, color=COLOR_OFFLINE)
            buttons = [PanelButton(START, server_id)]

        embed.add_field(name='Address', value=f'`{display_address(server)}`')
        if running and pending is None:
            embed.add_field(name='Version', value=stats.get('version') or '-')
            embed.add_field(name='Players', value=player_text(stats)[:MAX_FIELD_LENGTH], inline=False)
            eta = self.auto_stop_eta(server_id)
            if stats.get('online'):
                embed.add_field(name='Stop & restart', value='possible once nobody is online', inline=False)
            elif eta is not None:
                embed.add_field(name='Auto stop', value=f'<t:{int(eta)}:R> if nobody joins', inline=False)
        embed.set_footer(text=f'{PANEL_FOOTER} · {server_id}')

        view = discord.ui.View(timeout=None)
        for button in buttons:
            view.add_item(button)
        return embed, view

    # ---- messages

    async def _channel(self, channel_id: int):
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)
        return channel

    async def _find(self, server_id: str, channel) -> discord.Message | None:
        """
        The panel message of the server in the channel: the stored one, or else one found in the channel history.
        """
        message = self.messages.get(server_id)
        if message is not None and message.channel.id == channel.id:
            return message
        stored = self.state.get(server_id)
        if stored and stored[0] == channel.id:
            try:
                return await channel.fetch_message(stored[1])
            except discord.NotFound:
                pass
        footer = f'{PANEL_FOOTER} · {server_id}'
        async for message in channel.history(limit=100):
            if (message.author.id == self.bot.user.id and message.embeds
                    and message.embeds[0].footer.text == footer):
                return message
        return None

    async def _remove(self, server_id: str) -> None:
        """
        Delete the panel of a server that has no channel anymore or moved to another one.
        """
        stored = self.state.pop(server_id, None)
        self.messages.pop(server_id, None)
        self.shown.pop(server_id, None)
        self._save()
        if not stored:
            return
        try:
            channel = await self._channel(stored[0])
            message = await channel.fetch_message(stored[1])
            await message.delete()
        except discord.HTTPException:
            pass

    async def _show(self, server: dict, stats: dict | None, channel_id: int) -> None:
        server_id = server['server_id']
        embed, view = self._content(server, stats)
        key = (channel_id, json.dumps(embed.to_dict(), sort_keys=True), json.dumps(view.to_components()))
        repost = server_id in self.repost
        self.repost.discard(server_id)
        if self.shown.get(server_id) == key and not repost:
            return

        stored = self.state.get(server_id)
        if stored and stored[0] != channel_id:
            await self._remove(server_id)

        name = server.get('server_name', server_id)
        try:
            channel = await self._channel(channel_id)
            if not hasattr(channel, 'send') or not hasattr(channel, 'history'):
                print(f'panel: {channel_id} ({getattr(channel, "name", "?")}) is not a text channel, '
                      f'no panel for {name}')
                return
            message = await self._find(server_id, channel)
            if message is not None and repost:
                # post it again below the newer messages (silently, no push notification), then remove the old one
                old, message = message, await channel.send(embed=embed, view=view, silent=True)
                print(f'panel: moved the panel of {name} down in #{channel}')
                try:
                    await old.delete()
                except discord.HTTPException:
                    pass
            elif message is not None:
                try:
                    message = await message.edit(embed=embed, view=view)
                except discord.NotFound:
                    message = None
            if message is None:
                message = await channel.send(embed=embed, view=view, silent=True)
                print(f'panel: posted the panel of {name} in #{channel}')
        except discord.Forbidden as e:
            print(f'panel: no permission to show the panel of {name} in channel {channel_id}, the bot needs '
                  f'View Channel, Send Messages, Embed Links and Read Message History there ({e})')
            return
        except discord.NotFound:
            print(f'panel: channel {channel_id} of {name} not found, was it deleted?')
            return
        except discord.HTTPException as e:
            print(f'panel: failed to show the panel of {name} in channel {channel_id}: {e}')
            return

        self.messages[server_id] = message
        self.shown[server_id] = key
        if self.state.get(server_id) != [channel_id, message.id]:
            self.state[server_id] = [channel_id, message.id]
            self._save()

    async def update(self, only: str | None = None) -> None:
        """
        Show the panel of every server with its own channel, or only of one server.
        """
        channels = panel_channels()
        async with self.lock:
            # servers without a channel (or no longer available in the bot) lose their panel
            servers = await get_servers()
            if servers is None:
                print('panel: failed to get server list')
                return
            available = {server['server_id']: server for server in servers if server['server_id'] in channels}
            if only is None:
                self._report(channels, available)
            if only is None:
                for server_id in [server_id for server_id in self.state if server_id not in available]:
                    await self._remove(server_id)
            if only is None and panel_mode() == BOTTOM:
                await self._check_bottom(available, channels)
            targets = [server for server_id, server in available.items() if only in (None, server_id)]
            stats = await asyncio.gather(*(get_server_stats(server['server_id']) for server in targets))
            for server, server_stats in zip(targets, stats):
                await self._show(server, server_stats, channels[server['server_id']])

    def _report(self, channels: dict[str, int], available: dict[str, dict]) -> None:
        """
        Log which servers get a panel, and why a server with a channel does not, whenever that changes.
        """
        setup = (tuple(sorted(channels.items())), tuple(sorted(available)))
        if setup == self.reported:
            return
        self.reported = setup
        if not channels:
            print('panel: no server has its own channel')
            return
        for server_id, channel_id in channels.items():
            server = available.get(server_id)
            if server is None:
                print(f'panel: server {server_id} has channel {channel_id} but is not available in the bot: '
                      f'tick it under "Verfügbare Server" or check that it still exists in Crafty')
            else:
                print(f'panel: {server.get("server_name", server_id)} has its own channel {channel_id}')

    # ---- buttons

    async def _allowed(self, interaction: discord.Interaction) -> bool:
        role_id = control_role_id()
        if not role_id or await self.bot.is_owner(interaction.user):
            return True
        return any(role.id == role_id for role in getattr(interaction.user, 'roles', []))

    async def click(self, interaction: discord.Interaction, action: str, server_id: str) -> None:
        if panel_channels().get(server_id) != interaction.channel_id:
            await interaction.response.send_message('This panel is not active anymore', ephemeral=True)
            return
        if not await self._allowed(interaction):
            await interaction.response.send_message(f'You need the <@&{control_role_id()}> role to do that',
                                                    ephemeral=True)
            return
        if server_id in self.busy:
            await interaction.response.send_message('Already in progress, one moment', ephemeral=True)
            return

        # acknowledge without a new message, answers to the user are ephemeral follow-ups
        await interaction.response.defer()

        async def reply(text: str) -> None:
            try:
                await interaction.followup.send(text, ephemeral=True)
            except discord.HTTPException as e:
                print(f'panel: failed to answer {interaction.user}: {e}')

        self.busy.add(server_id)
        try:
            server = next((s for s in await get_servers() or [] if s['server_id'] == server_id), None)
            if server is None:
                await reply('Server not available')
                return
            user = interaction.user.mention
            if action == START:
                async def progress(text: str) -> None:
                    self.pending[server_id] = Pending(text, START, time.time() + PENDING_TIMEOUT)
                    await self.update(server_id)

                ok = await self.start_action(server, user, reply, progress)
                if not ok:
                    self.pending.pop(server_id, None)
            elif action == STOP:
                ok = await self.stop_action(server_id, user, reply)
                if ok:
                    self.pending[server_id] = Pending('Stopping', STOP, time.time() + PENDING_TIMEOUT)
            else:
                before = await get_server_stats(server_id)
                ok = await self.restart_action(server_id, user, reply)
                if ok:
                    self.pending[server_id] = Pending('Restarting', RESTART, time.time() + PENDING_TIMEOUT,
                                                      started=(before or {}).get('started'))
            await self.update(server_id)
        finally:
            self.busy.discard(server_id)

    # ---- other messages in panel channels

    async def clean(self, message: discord.Message) -> None:
        """
        Delete a message someone else wrote in a panel channel.
        """
        try:
            await message.delete()
        except discord.NotFound:
            pass
        except discord.HTTPException as e:
            if not self.warned_delete:
                self.warned_delete = True
                print(f'panel: cannot delete messages in #{message.channel}, '
                      f'the bot needs the "Manage Messages" permission there ({e})')

    # ---- keeping the panels below other messages (panel.mode bottom)

    def _panel_ids(self, channel_id: int) -> dict[int, str]:
        """
        Message ID -> server ID of the panels in the channel.
        """
        return {message_id: server_id for server_id, (panel_channel, message_id) in self.state.items()
                if panel_channel == channel_id}

    async def _check_bottom(self, available: dict[str, dict], channels: dict[str, int]) -> None:
        """
        Post the panels again if other messages came after them, e.g. while the bot was offline.
        """
        for channel_id in set(channels[server_id] for server_id in available):
            panels = self._panel_ids(channel_id)
            if not panels:
                continue
            try:
                channel = await self._channel(channel_id)
                last = getattr(channel, 'last_message_id', None)
                if last in panels or self.checked.get(channel_id) == last:
                    continue
                self.checked[channel_id] = last
                # the last message ID may belong to a deleted message, so look at what really comes after the panels
                newer = [message async for message in channel.history(after=discord.Object(min(panels)), limit=20)
                         if message.id not in panels]
            except discord.HTTPException as e:
                print(f'panel: failed to read the messages in {channel_id}: {e}')
                continue
            if newer:
                self.repost.update(panels.values())

    def notice(self, message: discord.Message) -> None:
        """
        A new message from someone else in a panel channel: post the panels below it, once the channel is quiet.
        """
        channel_id = message.channel.id
        task = self.repost_tasks.get(channel_id)
        if task is not None:
            task.cancel()
        self.repost_tasks[channel_id] = asyncio.create_task(self._repost_later(channel_id))

    async def _repost_later(self, channel_id: int) -> None:
        try:
            await asyncio.sleep(REPOST_DELAY)
        except asyncio.CancelledError:
            return
        self.repost_tasks.pop(channel_id, None)
        if panel_mode() != BOTTOM:
            return
        self.repost.update(self._panel_ids(channel_id).values())
        try:
            await self.update()
        except Exception as e:  # keep the bot running on unexpected errors
            print(f'panel: failed to move the panels in {channel_id} down: {e}')
