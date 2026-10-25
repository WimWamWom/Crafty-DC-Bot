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
from core.web import WebInterface
from core.backup import BackupScheduler, backup_before_start, mark_started, needs_start_backup
from core.motd import set_random_motd
from core.address import has_free_domain, prepare_start
from core.constants import (GUILD_ID, WEB_PORT, auto_stop_enabled, auto_stop_idle_time, session_channel_id,
                            session_enabled, status_channel_id, status_update_interval)


class CraftyBot(commands.Bot):
    async def setup_hook(self) -> None:
        # setup_hook runs once per process, unlike on_ready which fires again after every reconnect
        # the loops always run and check their setting on every run, so it can be changed without a restart
        auto_stop.start()
        update_status.start()
        update_sessions.start()
        backup_loop.start()

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


sessions = SessionTracker(bot, session_channel_id, auto_stop_eta, set_random_motd)


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


@auto_stop.before_loop
@update_status.before_loop
@update_sessions.before_loop
@backup_loop.before_loop
async def wait_until_ready():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print('Bot is ready. {}'.format(bot.user))
    print("Crafty Bot version 0.2.0")
    print("Server URL: {}".format(get('crafty.url')))
    print("GUILD ID: {}".format(GUILD_ID))


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


# start a server
@bot.hybrid_command(name='start', description='start a server')
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.autocomplete(server_id=get_stopped_server_list)
@control_role()
async def start(ctx, server_id):
    print('start')

    if not await check_server_id(server_id, ctx):
        return

    await ctx.defer(ephemeral=True)
    # check if server is already running
    running = await is_server_running(server_id)
    if running is None:
        await ctx.reply('failed to get server stats', ephemeral=True)
        return
    if running:
        await ctx.reply('Server already running', ephemeral=True)
        return

    # check before the backup, prepare_start checks again and takes the domain
    free = await has_free_domain(server_id)
    if not free:
        await ctx.reply('failed to check which domains are free' if free is None
                        else 'No free domain for this server, stop a server first', ephemeral=True)
        return

    backup = needs_start_backup(server_id)
    session = None
    if session_enabled():
        server = next((s for s in await get_cached_servers() or [] if s['server_id'] == server_id),
                      {'server_id': server_id, 'server_name': server_id})
        # the embed is the public answer, as a reply to the message for > commands
        session = await sessions.begin(server, ctx.author.mention, ctx.channel, backup,
                                       reference=ctx.message if ctx.interaction is None else None)
        if ctx.interaction is not None:
            link = f': {session.message.jump_url}' if session.message else ''
            await ctx.reply(f'Starting {server["server_name"]}{link}', ephemeral=True)

    if backup:
        if session is None:
            await ctx.reply('Creating a backup before starting, this can take a moment...', ephemeral=True)
        backup_ok = await backup_before_start(server_id)
        if session is not None:
            await sessions.update(session, phase=STARTING,
                                  note=None if backup_ok else 'Backup failed, check the backups in Crafty')
        elif not backup_ok:
            await ctx.reply('Backup failed, starting the server anyway. Check the backups in Crafty', ephemeral=True)

    domain, error = await prepare_start(server_id)
    if error is not None:
        if session is not None:
            await sessions.fail(session, error)
        await ctx.reply(f'failed to start server: {error}', ephemeral=True)
        return
    if domain is not None and session is not None:
        await sessions.update(session, address=domain)

    if await server_action(server_id, 'start_server'):
        mark_started(server_id)
        if session is None:
            await ctx.reply('Server started', ephemeral=True)
    else:
        if session is not None:
            await sessions.fail(session, 'failed to start')
        await ctx.reply('failed to start server', ephemeral=True)


async def check_can_stop(ctx, server_id, action: str) -> bool:
    """
    Check that the server is running and no players are online, and tell the user if not.
    """
    running = await is_server_running(server_id)
    if running is None:
        await ctx.reply('failed to get server stats', ephemeral=True)
        return False
    if not running:
        await ctx.reply('Server already stopped', ephemeral=True)
        return False

    player_count = await get_player_count(server_id)
    if player_count == -1:
        await ctx.reply('failed to get server stats', ephemeral=True)
        return False
    if player_count != 0:
        await ctx.reply(f'cannot {action} server: {player_count} Player(s) online', ephemeral=True)
        return False
    return True


# stop a server
@bot.hybrid_command(name='stop', description='stop a server')
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.autocomplete(server_id=get_running_server_list)
@control_role()
async def stop(ctx, server_id):
    print('stop')

    if not await check_server_id(server_id, ctx):
        return

    await ctx.defer(ephemeral=True)
    if not await check_can_stop(ctx, server_id, 'stop'):
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

    await ctx.defer(ephemeral=True)
    if not await check_can_stop(ctx, server_id, 'restart'):
        return

    sessions.mark_restart(server_id)
    await set_random_motd(server_id)
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
