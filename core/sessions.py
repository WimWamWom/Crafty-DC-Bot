"""
This module keeps one message per server start ("session") in a Discord channel.

The message shows the backup before the start, then the running server with its players and the time until
auto stop, and finally why and when the server was stopped. It stays in the channel after the stop.
"""

import asyncio
import time
from dataclasses import dataclass, field

import discord

from core.address import display_address
from core.embeds import COLOR_OFFLINE, COLOR_ONLINE, MAX_FIELD_LENGTH, add_usage_fields, new_embed, player_text
from core.server import get_server_stats, get_servers

# Footer text used to find session messages again after a restart, followed by the server ID
SESSION_FOOTER = 'Crafty server session'

COLOR_PENDING = discord.Color.gold()

# a started server that does not show up as running after this time is reported as failed
START_TIMEOUT = 300

BACKUP = 'backup'
STARTING = 'starting'
RUNNING = 'running'
STOPPED = 'stopped'


@dataclass
class Session:
    server_id: str
    name: str
    address: str
    started_by: str | None = None
    phase: str = STARTING
    # when the start was requested, and when the server was first seen running
    requested_at: float = field(default_factory=time.time)
    started_at: float | None = None
    stopped_at: float | None = None
    stop_reason: str = ''
    note: str = ''
    stats: dict | None = None
    message: discord.Message | None = None


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours} h {minutes} min' if hours else f'{minutes} min'


class SessionTracker:
    """
    Posts a message when a server starts and edits it until the server is stopped.

    Args:
        bot: The Discord bot.
        channel_id: Function that returns the channel for servers started outside the bot, and for all sessions
            if set. 0 = none. Read on every use, so a changed setting takes effect at once.
        auto_stop_eta: Function that returns the time (epoch seconds) when auto stop will stop a server
            if nobody joins, or None if auto stop is off.
        on_stop: Coroutine function called with the server ID when a server is seen stopped.
    """

    def __init__(self, bot: discord.Client, channel_id, auto_stop_eta=None, on_stop=None):
        self.bot = bot
        self._channel_id = channel_id
        self.auto_stop_eta = auto_stop_eta or (lambda server_id: None)
        self.on_stop = on_stop
        self.tasks: set[asyncio.Task] = set()
        self.sessions: dict[str, Session] = {}
        # reasons for stops requested by the bot, used when the server is seen stopped
        self.stop_reasons: dict[str, str] = {}
        # servers restarted by the bot: being stopped for a moment does not end their session until then
        self.restarting: dict[str, float] = {}
        self.restored = False
        self.lock = asyncio.Lock()

    @property
    def channel_id(self) -> int:
        return self._channel_id()

    # ---- embed

    def _embed(self, session: Session) -> discord.Embed:
        if session.phase == BACKUP:
            embed = new_embed(title=session.name, description='💾 Creating backup, the server starts afterwards',
                              color=COLOR_PENDING)
        elif session.phase == STARTING:
            embed = new_embed(title=session.name, description='⏳ Starting', color=COLOR_PENDING)
        elif session.phase == RUNNING:
            embed = new_embed(title=session.name, description='🟢 Online', color=COLOR_ONLINE)
        else:
            embed = new_embed(title=session.name, description=f'🔴 Stopped: {session.stop_reason}',
                              color=COLOR_OFFLINE)

        embed.add_field(name='Address', value=f'`{session.address}`')
        if session.started_by:
            embed.add_field(name='Started by', value=session.started_by)

        stats = session.stats or {}
        if session.phase == RUNNING:
            embed.add_field(name='Version', value=stats.get('version') or '-')
            embed.add_field(name='Players', value=player_text(stats)[:MAX_FIELD_LENGTH], inline=False)
            add_usage_fields(embed, stats)
            embed.add_field(name='Online since', value=f'<t:{int(session.started_at)}:R>')
            eta = self.auto_stop_eta(session.server_id)
            if eta is not None:
                if stats.get('online'):
                    embed.add_field(name='Auto stop', value='paused while players are online')
                else:
                    embed.add_field(name='Auto stop', value=f'<t:{int(eta)}:R> if nobody joins')
        elif session.phase == STOPPED and session.started_at:
            embed.add_field(name='Online', value=(f'<t:{int(session.started_at)}:t> – <t:{int(session.stopped_at)}:t> '
                                                  f'({_duration(session.stopped_at - session.started_at)})'))

        if session.note:
            embed.add_field(name='Note', value=session.note, inline=False)
        embed.set_footer(text=f'{SESSION_FOOTER} · {session.server_id}')
        return embed

    async def _channel(self, channel_id: int):
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)
        return channel

    async def _show(self, session: Session, channel=None, reference: discord.Message | None = None) -> None:
        """
        Post the session message, or edit it if it was already posted.
        """
        embed = self._embed(session)
        try:
            if session.message is not None:
                if session.message.embeds and session.message.embeds[0].to_dict() == embed.to_dict():
                    return
                session.message = await session.message.edit(embed=embed)
                return
            if channel is None:
                if not self.channel_id:
                    return
                channel = await self._channel(self.channel_id)
            session.message = await channel.send(embed=embed, reference=reference, mention_author=False)
        except discord.NotFound:
            # message was deleted: keep the session but stop showing it
            session.message = None
        except discord.HTTPException as e:
            print(f'session: failed to show message for {session.name}: {e}')

    # ---- called by the commands

    async def begin(self, server: dict, started_by: str, channel, backup: bool,
                    reference: discord.Message | None = None) -> Session:
        """
        Start a session for /start and post its message.
        """
        async with self.lock:
            session = Session(server['server_id'], server['server_name'], display_address(server),
                              started_by=started_by, phase=BACKUP if backup else STARTING)
            self.sessions[session.server_id] = session
            if self.channel_id:
                channel, reference = None, None
            await self._show(session, channel, reference)
            return session

    async def update(self, session: Session, phase: str | None = None, note: str | None = None,
                     address: str | None = None) -> None:
        async with self.lock:
            if address is not None:
                session.address = address
            if phase is not None:
                session.phase = phase
                session.requested_at = time.time()
            if note is not None:
                session.note = note
            await self._show(session)

    async def fail(self, session: Session, reason: str) -> None:
        async with self.lock:
            self._finish(session, reason)
            await self._show(session)

    def set_stop_reason(self, server_id: str, reason: str | None) -> None:
        if reason is None:
            self.stop_reasons.pop(server_id, None)
        else:
            self.stop_reasons[server_id] = reason

    def mark_restart(self, server_id: str) -> None:
        self.restarting[server_id] = time.time() + START_TIMEOUT

    def _finish(self, session: Session, reason: str) -> None:
        session.phase = STOPPED
        session.stopped_at = time.time()
        session.stop_reason = reason
        self.sessions.pop(session.server_id, None)
        self.stop_reasons.pop(session.server_id, None)

    # ---- periodic update

    async def _restore(self, servers: list[dict]) -> None:
        """
        Find the session messages of the last run, so a restart of the bot does not post them again.
        """
        self.restored = True
        if not self.channel_id:
            return
        names = {server['server_id']: server for server in servers}
        found: dict[str, discord.Message] = {}
        try:
            channel = await self._channel(self.channel_id)
            async for message in channel.history(limit=100):
                if message.author.id != self.bot.user.id or not message.embeds:
                    continue
                footer = message.embeds[0].footer.text or ''
                if footer.startswith(SESSION_FOOTER + ' · '):
                    # history is newest first: keep the latest message per server
                    found.setdefault(footer.split(' · ', 1)[1], message)
        except discord.HTTPException as e:
            print(f'session: failed to read channel history: {e}')
            return

        for server_id, message in found.items():
            embed = message.embeds[0]
            if server_id not in names or embed.description.startswith('🔴'):
                continue
            started_at = next((int(f.value[3:-3]) for f in embed.fields
                               if f.name == 'Online since' and f.value.startswith('<t:')), None)
            started_by = next((f.value for f in embed.fields if f.name == 'Started by'), None)
            self.sessions[server_id] = Session(server_id, names[server_id]['server_name'],
                                               display_address(names[server_id]), started_by=started_by,
                                               phase=RUNNING, started_at=started_at or time.time(), message=message)

    async def tick(self) -> None:
        servers = await get_servers()
        if servers is None:
            print('session: failed to get server list')
            return
        stats = await asyncio.gather(*(get_server_stats(server['server_id']) for server in servers))

        async with self.lock:
            if not self.restored:
                await self._restore(servers)

            for server, server_stats in zip(servers, stats):
                if server_stats is None:
                    continue
                server_id = server['server_id']
                running = bool(server_stats.get('running'))
                session = self.sessions.get(server_id)

                if session is None:
                    if running:
                        # started outside the bot, e.g. in Crafty, or before the bot started
                        session = Session(server_id, server['server_name'], display_address(server), phase=RUNNING,
                                          started_at=time.time(), stats=server_stats)
                        self.sessions[server_id] = session
                        await self._show(session)
                    continue

                session.stats = server_stats
                if session.phase == BACKUP:
                    continue
                if session.phase == STARTING:
                    if running:
                        session.phase = RUNNING
                        session.started_at = time.time()
                    elif time.time() - session.requested_at > START_TIMEOUT:
                        self._finish(session, 'did not start, check the server in Crafty')
                elif running:
                    self.restarting.pop(server_id, None)
                elif time.time() < self.restarting.get(server_id, 0):
                    # restarted by the bot and not up again yet
                    continue
                else:
                    self.restarting.pop(server_id, None)
                    if server_stats.get('crashed'):
                        reason = '💥 crashed'
                    else:
                        reason = self.stop_reasons.get(server_id, 'stopped outside the bot')
                    self._finish(session, reason)
                    if self.on_stop is not None:
                        task = asyncio.create_task(self.on_stop(server_id))
                        self.tasks.add(task)
                        task.add_done_callback(self.tasks.discard)
                await self._show(session)
