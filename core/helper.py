"""
This module contains helper different functions.
"""

import time
import uuid

import discord
from discord import app_commands

from core.config import config, missing_required
from core.constants import ALLOWED_SERVERS
from core.server import get_servers


def check_config() -> bool:
    """
    Check if all required settings are set.

    The required settings are the Crafty URL, the Crafty API token and the Discord bot token.
    They can be set in the config file, the web interface or the environment variables
    SERVER_URL, CRAFTY_TOKEN and DISCORD_TOKEN.

    Returns:
        bool: True if the bot can start, False otherwise.
    """
    missing = missing_required(config)
    if missing:
        print('Not all required settings set')
        for label in missing:
            print(f'{label} not set')
        return False

    if not config['discord.guild_id']:
        print('Discord server ID (GUILD_ID) not set: slash commands will not be available')

    print('All required settings set')
    return True


async def check_server_id(server_id: str, ctx=None) -> bool:
    """
    Check if the server ID is valid.

    Args:
        server_id (str): The server ID to check.
        ctx (commands.Context): The context of the command.

    Returns:
        bool: True if the server ID is valid, False otherwise.
    """

    try:
        print('Checking server ID')
        uuid.UUID(server_id, version=4)
    except ValueError:
        print('Invalid server ID')
        if ctx:
            await ctx.reply('Invalid server ID', ephemeral=True)
        return False
    if ALLOWED_SERVERS and server_id not in ALLOWED_SERVERS:
        print('Server not available')
        if ctx:
            await ctx.reply('Server not available', ephemeral=True)
        return False
    print('Valid server ID')
    return True


# Global variables for caching
cached_server_list = None
cache_timestamp = 0
CACHE_DURATION = 60  # Cache duration in seconds (e.g., 1 minute)


async def get_cached_servers() -> list[dict] | None:
    """
    Get the server list, cached for CACHE_DURATION seconds.
    """
    global cached_server_list, cache_timestamp

    # Check if the cache is still valid
    if cached_server_list is not None and (time.time() - cache_timestamp) < CACHE_DURATION:
        return cached_server_list

    servers = await get_servers()
    if servers is not None:
        cached_server_list = servers
        cache_timestamp = time.time()
    return servers


async def get_server_name(server_id: str) -> str:
    """
    Get the name of the server with the specified ID, or the ID itself if it is unknown.
    """
    for server in await get_cached_servers() or []:
        if server['server_id'] == server_id:
            return server['server_name']
    return server_id


async def get_server_list(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    servers = await get_cached_servers()
    if servers is None:
        return [app_commands.Choice(name='failed to get server list', value='failed to get server list')]

    server_list = [app_commands.Choice(name=server['server_name'][:100], value=server['server_id'])
                   for server in servers
                   if server['server_name'].lower().startswith(current.lower())]
    # Discord allows at most 25 choices
    return server_list[:25]
