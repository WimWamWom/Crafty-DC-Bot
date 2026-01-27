"""
This is the main file of the bot. It contains the
main loop and the event handlers.
"""

import asyncio
import os
import sys

import discord
from discord.ext import commands
from discord import app_commands
from discord.ext.commands import is_owner
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Load environment variables from .env file
load_dotenv()
from core.helper import check_env_vars, check_server_id, get_server_list

check_env_vars()

from core.network import get_json_response, HttpMethod
from core.printing import print_server_info, print_server_status
from core.server import is_server_running, stop_server, get_player_count
from core.custom_help_command import CustomHelpCommand
from core.constants import AUTO_STOP_SLEEP_TIME, GUILD_ID, API_ENDPOINT

SERVER_URL = os.environ['SERVER_URL']
if 'USERNAME' in os.environ and 'PASSWORD' in os.environ:
    USERNAME = os.environ['USERNAME']
    PASSWORD = os.environ['PASSWORD']

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='>', intents=intents, help_command=CustomHelpCommand())


# stop server after 1 hour of inactivity (no players online)
async def auto_stop():
    """
    Automatically stop servers that have been inactive for a certain period of time.
    """
    # track consecutive zero-player checks per server
    consecutive_zero = {}
    while True:
        # get list of servers ids and loop through them and add only the ones that are running
        data = get_json_response(API_ENDPOINT,
                                 'failed to get server list')
        if not data:
            print('failed to get server list')
            return
        server_ids = [server['server_id'] for server in data['data']]

        for server_id in server_ids:
            # if server not running, clear any counters and continue
            if not is_server_running(server_id):
                consecutive_zero.pop(server_id, None)
                continue

            player_count = get_player_count(server_id)
            # get_player_count returns -1 on error; skip counting in that case
            if player_count == -1:
                continue

            if player_count == 0:
                consecutive_zero[server_id] = consecutive_zero.get(server_id, 0) + 1
                # require two consecutive checks with 0 players before stopping
                if consecutive_zero[server_id] >= 2:
                    stop_server(server_id)
                    consecutive_zero.pop(server_id, None)
            else:
                # players online -> reset counter
                consecutive_zero[server_id] = 0

        await asyncio.sleep(AUTO_STOP_SLEEP_TIME)  # task runs every hour


@bot.event
async def on_ready():
    print('Bot is ready. {}'.format(bot.user))
    print("Crafty Bot version 0.1.1")
    print("Server URL: {}".format(SERVER_URL))
    print("GUILD ID: {}".format(GUILD_ID))

    try:
        # accept common truthy values (case-insensitive) and run auto_stop in background
        if os.environ.get('ENABLE_AUTO_STOP_SERVER', '').lower() in ('1', 'true', 'yes', 'on'):
            print('auto stop enabled')
            bot.loop.create_task(auto_stop())
        else:
            print('auto stop disabled')
    except Exception as e:
        print(e)
    # Synchronize slash commands on startup
    try:
        synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"{len(synced)} commands synced on startup.")
    except Exception as e:
        print(f"Failed to sync commands on startup: {e}")


@bot.hybrid_command(name='sync', description='Sync slash commands')
@app_commands.guilds(discord.Object(id=GUILD_ID))
@is_owner()
async def sync(ctx) -> None:
    print('sync')
    synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    # add commands to the app commands
    await ctx.reply("{} commands synced".format(len(synced)), ephemeral=True)


@bot.hybrid_command(name='clear', description='Clear all slash commands')
@app_commands.guilds(discord.Object(id=GUILD_ID))
@is_owner()
async def clear(ctx) -> None:
    print('clear')
    bot.tree.clear_commands(guild=discord.Object(id=GUILD_ID))
    await ctx.reply("All commands cleared", ephemeral=True)


@bot.hybrid_command(name='commands', description='Get all slash commands')
@app_commands.guilds(discord.Object(id=GUILD_ID))
@is_owner()
async def get_commands(ctx) -> None:
    print('commands')
    get_all_commands = bot.tree.get_commands(guild=discord.Object(id=GUILD_ID))
    await ctx.reply(f"Got {len(get_all_commands)} commands", ephemeral=True)


@bot.hybrid_command(name='get_token', description='get token if not set (not recommended)')
@app_commands.guilds(discord.Object(id=GUILD_ID))
@is_owner()
async def get_token(ctx):
    print('get_token')

    data = get_json_response('/api/v2/auth/login', 'failed to get token')
    if not data:
        await ctx.reply('failed to get token', ephemeral=True)
        return

    os.environ['CRAFTY_TOKEN'] = data['data']['token']
    await ctx.send('Token successfully retrieved', ephemeral=True)


@bot.hybrid_command(name='list', description='get server list')
@app_commands.guilds(discord.Object(id=GUILD_ID))  # get the list of servers
async def get_list(ctx):
    print('servers')
    data = get_json_response('/api/v2/servers', 'failed to get server list')
    server_info_text = print_server_info(data)

    await ctx.reply(f"Serverinformationen:\n{server_info_text}", ephemeral=True)


# get statistics of a server
@bot.hybrid_command(name='stats', description='get server stats')
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.autocomplete(server_id=get_server_list)
async def stats(ctx, server_id):
    print('stats')

    if not await check_server_id(server_id, ctx):
        return

    data = get_json_response(API_ENDPOINT + str(server_id) + '/stats', 'failed to get server stats')
    if not data:
        await ctx.reply('failed to get server stats', ephemeral=True)
        return

    server_info_text = print_server_status(data)
    await ctx.reply(f"Serverinformationen:\n{server_info_text}", ephemeral=True)

# start a server
@bot.hybrid_command(name='start', description='start a server')
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.autocomplete(server_id=get_server_list)
async def start(ctx, server_id):
    print('start')

    if not await check_server_id(server_id, ctx):
        return

    # check if server is already running
    if is_server_running(server_id, ctx):
        await ctx.reply('Server already running', ephemeral=True)
        return

    data = get_json_response(API_ENDPOINT + str(server_id) + '/action/start_server',
                             'failed to start server', method=HttpMethod.POST)
    if not data:
        await ctx.reply('failed to start server', ephemeral=True)
        return

    if data['status'] == "ok":
       await ctx.reply('Server started', ephemeral=True)


# stop a server
@bot.hybrid_command(name='stop', description='stop a server')
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.autocomplete(server_id=get_server_list)
async def stop(ctx, server_id):
    print('stop')

    if not await check_server_id(server_id, ctx):
        return

    # check if server is already stopped
    if not is_server_running(server_id, ctx):
        await ctx.reply('Server already stopped', ephemeral=True)
        return

    # check if player is online
    player_count = get_player_count(server_id, ctx)
    if player_count != 0:
        await ctx.reply(f'cannot stop server: {player_count} Player(s) online', ephemeral=True)
        return

    if stop_server(server_id):
        await ctx.reply('Server stopped', ephemeral=True)
    else:
        await ctx.reply('failed to stop server', ephemeral=True)


# restart a server
@bot.hybrid_command(name='restart', description='restart a server')
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.autocomplete(server_id=get_server_list)
async def restart(ctx, server_id):
    print('restart')

    if not await check_server_id(server_id, ctx):
        return

    # check if server is already stopped
    if not is_server_running(server_id, ctx):
        await ctx.reply('Server already stopped', ephemeral=True)
        return

    # check if player is online
    player_count = get_player_count(server_id, ctx)
    if player_count != 0:
        await ctx.reply(f'cannot restart server: {player_count} Player(s) online', ephemeral=True)
        return

    if stop_server(server_id):
        await ctx.reply('Server stopped', ephemeral=True)
    else:
        await ctx.reply('failed to stop server', ephemeral=True)

    data = get_json_response(API_ENDPOINT + str(server_id) + '/action/restart_server',
                             'failed to restart server', method=HttpMethod.POST)
    if not data:
        await ctx.reply('failed to start server', ephemeral=True)
        return

    if data['status'] == "ok":
        await ctx.reply('Server restarted', ephemeral=True)

# command not found
@bot.event
async def on_command_error(ctx, error):
    """
    Handle command errors
    """
    if isinstance(error, commands.CommandNotFound):
        await ctx.send('Command not found. Use `>help` to get a list of available commands.')
        print(error)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send('Missing required argument. Use `>help` to get a list of available commands.')
        print(error)


bot.run(os.environ['DISCORD_TOKEN'])
