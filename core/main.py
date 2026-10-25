"""
This is the main file of the bot. It contains the
main loop and the event handlers.
"""

import asyncio
import os
import sys
import traceback

import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ext.commands import is_owner
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Load environment variables from .env file (used for settings missing in the config file)
load_dotenv()
from core.config import get
from core.helper import check_config, check_server_id, get_server_list, get_cached_servers, get_server_name
from core.server import is_server_running, stop_server, get_player_count, get_server_stats, server_action
from core.embeds import server_list_embed, server_stats_embed
from core.status import StatusBoard
from core.checks import command_channel_check, control_role
from core.custom_help_command import CustomHelpCommand
from core.web import WebInterface
from core.constants import (AUTO_STOP_ENABLED, AUTO_STOP_SLEEP_TIME, GUILD_ID, STATUS_CHANNEL_ID,
                            STATUS_UPDATE_INTERVAL, WEB_PORT)

SERVER_URL = get('crafty.url')


class CraftyBot(commands.Bot):
    async def setup_hook(self) -> None:
        # setup_hook runs once per process, unlike on_ready which fires again after every reconnect
        if AUTO_STOP_ENABLED:
            print('auto stop enabled')
            auto_stop.start()
        else:
            print('auto stop disabled')

        if STATUS_CHANNEL_ID:
            print(f'status embed enabled in channel {STATUS_CHANNEL_ID}')
            update_status.start()

        # Synchronize slash commands on startup
        try:
            synced = await self.tree.sync(guild=discord.Object(id=GUILD_ID))
            print(f"{len(synced)} commands synced on startup.")
        except Exception as e:
            print(f"Failed to sync commands on startup: {e}")


intents = discord.Intents.default()
intents.message_content = True
bot = CraftyBot(command_prefix='>', intents=intents, help_command=CustomHelpCommand())
bot.add_check(command_channel_check)

status_board = StatusBoard(bot, STATUS_CHANNEL_ID)

# track consecutive zero-player checks per server
consecutive_zero = {}


# stop servers after AUTO_STOP_SLEEP_TIME to 2x AUTO_STOP_SLEEP_TIME of inactivity (no players online)
@tasks.loop(seconds=AUTO_STOP_SLEEP_TIME)
async def auto_stop():
    """
    Automatically stop servers that have been inactive for a certain period of time.
    """
    try:
        servers = await get_cached_servers()
        if servers is None:
            print('auto stop: failed to get server list, retrying next run')
            return

        for server in servers:
            server_id = server['server_id']
            stats = await get_server_stats(server_id)
            # skip counting on error
            if stats is None:
                continue

            # if server not running, clear any counters and continue
            if not stats.get('running'):
                consecutive_zero.pop(server_id, None)
                continue

            if stats.get('online', 0) == 0:
                consecutive_zero[server_id] = consecutive_zero.get(server_id, 0) + 1
                # require two consecutive checks with 0 players before stopping
                if consecutive_zero[server_id] >= 2:
                    if await stop_server(server_id):
                        print(f'auto stop: stopped {server["server_name"]}')
                    consecutive_zero.pop(server_id, None)
            else:
                # players online -> reset counter
                consecutive_zero[server_id] = 0
    except Exception:
        # keep the loop alive on unexpected errors
        traceback.print_exc()


@tasks.loop(seconds=STATUS_UPDATE_INTERVAL)
async def update_status():
    """
    Update the status embed in the status channel.
    """
    try:
        await status_board.update()
    except Exception:
        # keep the loop alive on unexpected errors (e.g. missing permissions)
        traceback.print_exc()


@auto_stop.before_loop
@update_status.before_loop
async def wait_until_ready():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print('Bot is ready. {}'.format(bot.user))
    print("Crafty Bot version 0.2.0")
    print("Server URL: {}".format(SERVER_URL))
    print("GUILD ID: {}".format(GUILD_ID))


@bot.hybrid_command(name='sync', description='Sync slash commands')
@app_commands.guilds(discord.Object(id=GUILD_ID))
@is_owner()
async def sync(ctx) -> None:
    print('sync')
    synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    await ctx.reply("{} commands synced".format(len(synced)), ephemeral=True)


@bot.hybrid_command(name='list', description='get server list')
@app_commands.guilds(discord.Object(id=GUILD_ID))  # get the list of servers
async def get_list(ctx):
    print('servers')
    await ctx.defer(ephemeral=True)
    servers = await get_cached_servers()
    if servers is None:
        await ctx.reply('failed to get server list', ephemeral=True)
        return

    await ctx.reply(embed=server_list_embed(servers), ephemeral=True)


# get statistics of a server
@bot.hybrid_command(name='stats', description='get server stats')
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.autocomplete(server_id=get_server_list)
async def stats(ctx, server_id):
    print('stats')

    if not await check_server_id(server_id, ctx):
        return

    await ctx.defer(ephemeral=True)
    data = await get_server_stats(server_id)
    if data is None:
        await ctx.reply('failed to get server stats', ephemeral=True)
        return

    await ctx.reply(embed=server_stats_embed(await get_server_name(server_id), data), ephemeral=True)


# start a server
@bot.hybrid_command(name='start', description='start a server')
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.autocomplete(server_id=get_server_list)
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

    if await server_action(server_id, 'start_server'):
        await ctx.reply('Server started', ephemeral=True)
    else:
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
@app_commands.autocomplete(server_id=get_server_list)
@control_role()
async def stop(ctx, server_id):
    print('stop')

    if not await check_server_id(server_id, ctx):
        return

    await ctx.defer(ephemeral=True)
    if not await check_can_stop(ctx, server_id, 'stop'):
        return

    if await stop_server(server_id):
        await ctx.reply('Server stopped', ephemeral=True)
    else:
        await ctx.reply('failed to stop server', ephemeral=True)


# restart a server
@bot.hybrid_command(name='restart', description='restart a server')
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.autocomplete(server_id=get_server_list)
@control_role()
async def restart(ctx, server_id):
    print('restart')

    if not await check_server_id(server_id, ctx):
        return

    await ctx.defer(ephemeral=True)
    if not await check_can_stop(ctx, server_id, 'restart'):
        return

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
        await ctx.send('Command not found. Use `>help` to get a list of available commands.')
        print(error)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send('Missing required argument. Use `>help` to get a list of available commands.')
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


async def main():
    await WebInterface(bot, on_saved=restart_process).start(WEB_PORT)

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
