"""
This is the main file of the bot. It contains the
main loop and the event handlers.
"""

import asyncio
import os
import sys
import time
import traceback

import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core import logtime
logtime.install()

# Load environment variables from .env file (used for settings missing in the config file)
load_dotenv()
from core.config import get
from core.config import RESTART_FIELDS
from core.helper import (clear_server_cache, check_config, check_server_id, get_cached_servers, get_running_server_list,
                         get_stopped_server_list)
from core.server import is_server_running, stop_server, get_player_count, get_server_stats, server_action
from core.embeds import new_embed, status_embed
from core.status import StatusBoard
from core.sessions import STARTING, SessionTracker
from core.checks import command_channel_check, control_role
from core.views import ServerStatsView
from core.panel import PanelButton, PanelBoard
from core.web import WebInterface
from core.backup import (BackupScheduler, backup_after_stop, backup_before_start, backup_while_running, mark_started,
                         needs_start_backup, wait_for_running_backup)
from core.icon import set_icon
from core.motd import set_motd
from core.address import has_free_domain, prepare_start
from core.constants import (GUILD_ID, WEB_PORT, auto_stop_enabled, auto_stop_idle_time, panel_channel_ids,
                            panel_channels, panel_mode, session_channel_id, session_enabled, status_channel_id,
                            status_update_interval)


class CraftyBot(commands.Bot):
    async def setup_hook(self) -> None:
        # setup_hook runs once per process, unlike on_ready which fires again after every reconnect
        # the loops always run and check their setting on every run, so it can be changed without a restart
        auto_stop.start()
        update_status.start()
        update_sessions.start()
        backup_loop.start()
        update_panels.start()
        # the panel buttons keep working after a restart
        self.add_dynamic_items(PanelButton)

        # Synchronize slash commands on startup
        try:
            synced = await self.tree.sync(guild=discord.Object(id=GUILD_ID))
            print(f"{len(synced)} commands synced on startup.")
        except Exception as e:
            print(f"Failed to sync commands on startup: {e}")


intents = discord.Intents.default()
intents.message_content = True
bot = CraftyBot(command_prefix='>', intents=intents, help_command=None)
bot.add_check(command_channel_check)

status_board = StatusBoard(bot, status_channel_id)
backup_scheduler = BackupScheduler()

# when each running server was first seen without players (epoch seconds)
empty_since = {}


def auto_stop_eta(server_id: str) -> float | None:
    """
    Time (epoch seconds) when auto stop will stop the server if nobody joins, or None if auto stop is off.
    """
    if not auto_stop_enabled():
        return None
    return empty_since.get(server_id, time.time()) + auto_stop_idle_time()


# start backups running in the background, kept so they are not garbage collected
background_tasks: set[asyncio.Task] = set()


async def start_backup_in_background(server_id: str, session) -> None:
    """
    Back up a server that was just started and show the progress in its start message.
    """
    if session is not None:
        await sessions.update(session, note='💾 Creating a backup once the server is up')
    ok = await backup_while_running(server_id)
    if session is not None:
        await sessions.update(session, note='💾 Backup created' if ok else 'Backup failed, check the backups in Crafty')


async def after_stop(server_id: str) -> None:
    """
    Prepare the next start of a stopped server, also when it is started from Crafty.
    """
    await set_motd(server_id)
    await set_icon(server_id)
    await backup_after_stop(server_id)


sessions = SessionTracker(bot, session_channel_id, auto_stop_eta, after_stop)


# stop servers auto_stop.idle_minutes after the last player left (or after the start if nobody joined)
@tasks.loop(seconds=60)
async def auto_stop():
    """
    Automatically stop servers that have been empty for auto_stop.idle_minutes.
    """
    if not auto_stop_enabled():
        empty_since.clear()
        return
    try:
        servers = await get_cached_servers()
        if servers is None:
            print('auto stop: failed to get server list, retrying next run')
            return

        for server in servers:
            server_id = server['server_id']
            stats = await get_server_stats(server_id)
            # keep the timer on error
            if stats is None:
                continue

            # not running or players online: no timer
            if not stats.get('running') or stats.get('online', 0) > 0:
                empty_since.pop(server_id, None)
                continue

            since = empty_since.setdefault(server_id, time.time())
            if time.time() - since >= auto_stop_idle_time():
                sessions.set_stop_reason(server_id, 'auto stop, nobody was online')
                if await stop_server(server_id):
                    print(f'auto stop: stopped {server["server_name"]}')
                    empty_since.pop(server_id, None)
                else:
                    sessions.set_stop_reason(server_id, None)
    except Exception:
        # keep the loop alive on unexpected errors
        traceback.print_exc()


@tasks.loop(seconds=status_update_interval())
async def update_status():
    """
    Update the status embed in the status channel.
    """
    try:
        await status_board.update()
    except Exception:
        # keep the loop alive on unexpected errors (e.g. missing permissions)
        traceback.print_exc()


@tasks.loop(seconds=30)
async def update_sessions():
    """
    Update the server start embeds.
    """
    if not session_enabled():
        return
    try:
        await sessions.tick()
    except Exception:
        # keep the loop alive on unexpected errors (e.g. missing permissions)
        traceback.print_exc()


@tasks.loop(seconds=60)
async def backup_loop():
    """
    Record which servers are online and run the scheduled backups.
    """
    await backup_scheduler.tick()


@tasks.loop(seconds=15)
async def update_panels():
    """
    Update the panels in the channels of the servers.
    """
    try:
        await panels.update()
    except Exception:
        # keep the loop alive on unexpected errors (e.g. missing permissions)
        traceback.print_exc()


@auto_stop.before_loop
@update_status.before_loop
@update_sessions.before_loop
@backup_loop.before_loop
@update_panels.before_loop
async def wait_until_ready():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print('Bot is ready. {}'.format(bot.user))
    print("Crafty Bot version 0.2.0")
    print("Server URL: {}".format(get('crafty.url')))
    print("GUILD ID: {}".format(GUILD_ID))


@bot.event
async def on_message(message: discord.Message):
    # a panel channel is for the panels: no command is answered there, other messages are deleted
    # or the panels are posted again below them
    if message.guild is not None and message.channel.id in panel_channel_ids():
        if message.author.id != bot.user.id:
            mode = panel_mode()
            if mode == 'delete':
                await panels.clean(message)
            elif mode == 'bottom':
                panels.notice(message)
        return
    await bot.process_commands(message)


@bot.hybrid_command(name='help', description='list all commands')
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def help_command(ctx):
    embed = new_embed(title='Commands', color=discord.Color.blurple())
    for command in sorted(bot.commands, key=lambda c: c.name):
        embed.add_field(name=f'/{command.name}', value=command.description or '-', inline=False)
    await ctx.reply(embed=embed, ephemeral=True)


# show the status of all servers with a dropdown to get the stats of one server
@bot.hybrid_command(name='stats', description='get server stats')
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def stats(ctx):
    print('stats')
    await ctx.defer(ephemeral=True)
    servers = await get_cached_servers()
    if servers is None:
        await ctx.reply('failed to get server list', ephemeral=True)
        return
    if not servers:
        await ctx.reply('No servers found', ephemeral=True)
        return

    server_stats = await asyncio.gather(*(get_server_stats(server['server_id']) for server in servers))
    embed = status_embed(list(zip(servers, server_stats)))
    # the footer marks the status board message, so this one must not have it
    embed.remove_footer()
    embed.description = 'Choose a server below to see its details'

    view = ServerStatsView(servers, ctx.author.id)
    view.message = await ctx.reply(embed=embed, view=view, ephemeral=True)


def panel_refusal(server_id: str) -> str | None:
    """
    Why a command must not control the server: it has its own channel and is only controlled with its panel there.
    """
    channel_id = panel_channels().get(server_id)
    if channel_id:
        return f'This server is controlled with the buttons in <#{channel_id}>'
    return None


async def start_flow(server: dict, started_by: str, reply, channel=None, reference=None, progress=None) -> bool:
    """
    Start a server: back it up if needed, give it a domain and its icon, and show the start in its session message.

    Args:
        server: The server from Crafty.
        started_by: Mention of the user who started it.
        reply: Coroutine function that sends a short answer only the user sees.
        channel: Channel for the session message if no session channel is set (None = none).
        reference: Message the session message answers (for > commands).
        progress: Coroutine function called with each step, used by the panel.

    Returns:
        bool: True if the server was started.
    """
    server_id = server['server_id']

    async def no_progress(text: str) -> None:
        pass

    progress = progress or no_progress

    # check if server is already running
    running = await is_server_running(server_id)
    if running is None:
        await reply('failed to get server stats')
        return False
    if running:
        await reply('Server already running')
        return False

    # check before the backup, prepare_start checks again and takes the domain
    free = await has_free_domain(server_id)
    if not free:
        await reply('failed to check which domains are free' if free is None
                    else 'No free domain for this server, stop a server first')
        return False

    mode = get('backup.mode')
    # with backups after the stop, the last one may still be running: the world must not change while it is zipped
    if mode == 'after_stop' and not await wait_for_running_backup(server_id, 0):
        await progress('Waiting for the backup of the last session')
        await reply('Waiting for the backup of the last session to finish...')
        if not await wait_for_running_backup(server_id, max(get('backup.timeout'), 30)):
            await reply('The backup of the last session is still running, try again later')
            return False
    backup = mode != 'after_stop' and needs_start_backup(server_id)
    # back up after the start instead of before it, once the server is up
    background_backup = backup and mode == 'background'
    session = None
    if session_enabled():
        # the embed is the public answer, as a reply to the message for > commands
        session = await sessions.begin(server, started_by, channel, backup and not background_backup,
                                       reference=reference)

    if backup and not background_backup:
        await progress('Creating a backup, the server starts afterwards')
        if session is None and channel is not None:
            await reply('Creating a backup before starting, this can take a moment...')
        backup_ok = await backup_before_start(server_id)
        if session is not None:
            await sessions.update(session, phase=STARTING,
                                  note=None if backup_ok else 'Backup failed, check the backups in Crafty')
        if not backup_ok:
            await reply('Backup failed, starting the server anyway. Check the backups in Crafty')

    await progress('Starting')
    domain, error = await prepare_start(server_id)
    if error is not None:
        if session is not None:
            await sessions.fail(session, error)
        await reply(f'failed to start server: {error}')
        return False
    if domain is not None and session is not None:
        await sessions.update(session, address=domain)
    await set_icon(server_id)

    if await server_action(server_id, 'start_server'):
        mark_started(server_id)
        if background_backup:
            task = asyncio.create_task(start_backup_in_background(server_id, session))
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)
        return True
    if session is not None:
        await sessions.fail(session, 'failed to start')
    await reply('failed to start server')
    return False


# start a server
@bot.hybrid_command(name='start', description='start a server')
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.autocomplete(server_id=get_stopped_server_list)
@control_role()
async def start(ctx, server_id):
    print('start')

    if not await check_server_id(server_id, ctx):
        return
    refusal = panel_refusal(server_id)
    if refusal:
        await ctx.reply(refusal, ephemeral=True)
        return

    await ctx.defer(ephemeral=True)
    server = next((s for s in await get_cached_servers() or [] if s['server_id'] == server_id),
                  {'server_id': server_id, 'server_name': server_id})

    async def reply(text: str) -> None:
        await ctx.reply(text, ephemeral=True)

    linked = False

    async def progress(text: str) -> None:
        # with a session message, a slash command gets its link once it is posted
        nonlocal linked
        session = sessions.sessions.get(server_id)
        if linked or session is None or ctx.interaction is None:
            return
        linked = True
        link = f': {session.message.jump_url}' if session.message else ''
        await reply(f'Starting {server["server_name"]}{link}')

    ok = await start_flow(server, ctx.author.mention, reply, channel=ctx.channel,
                          reference=ctx.message if ctx.interaction is None else None, progress=progress)
    if ok and not session_enabled():
        await reply('Server started')


async def check_can_stop(reply, server_id, action: str) -> bool:
    """
    Check that the server is running and no players are online, and tell the user if not.

    Args:
        reply: Coroutine function that sends a short answer only the user sees.
    """
    running = await is_server_running(server_id)
    if running is None:
        await reply('failed to get server stats')
        return False
    if not running:
        await reply('Server already stopped')
        return False

    player_count = await get_player_count(server_id)
    if player_count == -1:
        await reply('failed to get server stats')
        return False
    if player_count != 0:
        await reply(f'cannot {action} server: {player_count} Player(s) online')
        return False
    return True


async def panel_start(server: dict, started_by: str, reply, progress) -> bool:
    # the session message never goes into the panel channel, only into the session channel if one is set
    return await start_flow(server, started_by, reply, progress=progress)


async def panel_stop(server_id: str, stopped_by: str, reply) -> bool:
    if not await check_can_stop(reply, server_id, 'stop'):
        return False
    sessions.set_stop_reason(server_id, f'stopped by {stopped_by}')
    if await stop_server(server_id):
        return True
    sessions.set_stop_reason(server_id, None)
    await reply('failed to stop server')
    return False


async def panel_restart(server_id: str, restarted_by: str, reply) -> bool:
    if not await check_can_stop(reply, server_id, 'restart'):
        return False
    sessions.mark_restart(server_id)
    await set_motd(server_id)
    await set_icon(server_id)
    if await server_action(server_id, 'restart_server'):
        return True
    await reply('failed to restart server')
    return False


panels = PanelBoard(bot, auto_stop_eta, panel_start, panel_stop, panel_restart)


# stop a server
@bot.hybrid_command(name='stop', description='stop a server')
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.autocomplete(server_id=get_running_server_list)
@control_role()
async def stop(ctx, server_id):
    print('stop')

    if not await check_server_id(server_id, ctx):
        return
    refusal = panel_refusal(server_id)
    if refusal:
        await ctx.reply(refusal, ephemeral=True)
        return

    await ctx.defer(ephemeral=True)
    if not await check_can_stop(lambda text: ctx.reply(text, ephemeral=True), server_id, 'stop'):
        return

    sessions.set_stop_reason(server_id, f'/stop by {ctx.author.mention}')
    if await stop_server(server_id):
        await ctx.reply('Server stopped', ephemeral=True)
    else:
        sessions.set_stop_reason(server_id, None)
        await ctx.reply('failed to stop server', ephemeral=True)


# restart a server
@bot.hybrid_command(name='restart', description='restart a server')
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.autocomplete(server_id=get_running_server_list)
@control_role()
async def restart(ctx, server_id):
    print('restart')

    if not await check_server_id(server_id, ctx):
        return
    refusal = panel_refusal(server_id)
    if refusal:
        await ctx.reply(refusal, ephemeral=True)
        return

    await ctx.defer(ephemeral=True)
    if not await check_can_stop(lambda text: ctx.reply(text, ephemeral=True), server_id, 'restart'):
        return

    sessions.mark_restart(server_id)
    await set_motd(server_id)
    await set_icon(server_id)
    if await server_action(server_id, 'restart_server'):
        await ctx.reply('Server restarted', ephemeral=True)
    else:
        await ctx.reply('failed to restart server', ephemeral=True)


@bot.event
async def on_command_error(ctx, error):
    """
    Handle command errors
    """
    # unwrap errors raised inside commands or by the slash command layer
    while hasattr(error, 'original'):
        error = error.original

    if isinstance(error, commands.CommandNotFound):
        await ctx.send('Command not found. Use `/help` to get a list of available commands.')
        print(error)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send('Missing required argument. Use `/help` to get a list of available commands.')
        print(error)
    elif isinstance(error, commands.NotOwner):
        await ctx.reply('Only the bot owner can use this command', ephemeral=True)
    elif isinstance(error, (commands.CheckFailure, app_commands.CheckFailure)):
        await ctx.reply(str(error) or 'You are not allowed to use this command', ephemeral=True)
    else:
        traceback.print_exception(type(error), error, error.__traceback__)
        await ctx.reply('Something went wrong', ephemeral=True)


def restart_process():
    """
    Restart the bot process so a changed config takes effect.
    """
    sys.stdout.flush()
    os.execv(sys.executable, [sys.executable, '-u', os.path.abspath(__file__)])


def apply_config(changed: set[str]) -> bool:
    """
    Take over settings saved in the web interface. Most are read on every use, so only a few need a restart.

    Returns:
        bool: True if the bot restarts.
    """
    if changed & RESTART_FIELDS or not bot.is_ready():
        # give the browser time to receive the response before restarting
        asyncio.get_running_loop().call_later(1, restart_process)
        return True
    clear_server_cache()
    if 'status.update_interval' in changed:
        update_status.change_interval(seconds=status_update_interval())
    if any(name.startswith('panel.') or name == 'servers.allowed' for name in changed):
        # show new panels at once instead of with the next update
        task = asyncio.create_task(update_panels.coro())
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
    print(f'config: applied {len(changed)} changed settings without restart')
    return False


async def main():
    await WebInterface(bot, on_saved=apply_config).start(WEB_PORT)

    if not check_config():
        print(f'Open the web interface on port {WEB_PORT} to finish the setup')
        await asyncio.Event().wait()

    try:
        async with bot:
            await bot.start(get('discord.token'))
    except discord.LoginFailure:
        print(f'Invalid Discord token. Fix it in the web interface on port {WEB_PORT}')
        await asyncio.Event().wait()
    except discord.PrivilegedIntentsRequired:
        print('Enable the "Message Content Intent" for the bot in the Discord Developer Portal')
        await asyncio.Event().wait()
    except Exception:
        # e.g. Discord not reachable: keep the web interface up and try again later
        traceback.print_exc()
        print('Bot stopped, restarting in 60 seconds')
        await asyncio.sleep(60)
        restart_process()


asyncio.run(main())
