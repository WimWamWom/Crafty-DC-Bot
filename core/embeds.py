"""
This module builds the Discord embeds for the server information.
"""

import re

import discord

from core.constants import LOGO_URL
from core.server import parse_players

COLOR_ONLINE = discord.Color.green()
COLOR_OFFLINE = discord.Color.red()
COLOR_UNKNOWN = discord.Color.light_grey()

# Footer text used to find the status message again after a restart
STATUS_FOOTER = 'Crafty server status'

# Discord limits embed field values to 1024 characters
MAX_FIELD_LENGTH = 1024


def new_embed(**kwargs) -> discord.Embed:
    """
    Create an embed with the bot logo in the top left corner.
    """
    embed = discord.Embed(**kwargs)
    embed.set_author(name='Crafty Bot', icon_url=LOGO_URL)
    return embed


def player_text(stats: dict) -> str:
    """
    Format the online player count and names, e.g. "2/20: Steve, Alex".
    """
    count = f"{stats.get('online', 0)}/{stats.get('max', '?')}"
    players = parse_players(stats.get('players'))
    if not players:
        return count
    text = f"{count}: {', '.join(players)}"
    if len(text) > MAX_FIELD_LENGTH:
        text = text[:MAX_FIELD_LENGTH - 1] + '…'
    return text


# bytes per unit Crafty may use in its memory value
MEMORY_UNITS = {'B': 1, 'KB': 1024, 'MB': 1024 ** 2, 'GB': 1024 ** 3, 'TB': 1024 ** 4}


def memory_gb(mem) -> str:
    """
    Format the memory usage from Crafty in GB. Crafty sends either a number in MB or a text like "834.5MB".
    """
    if isinstance(mem, (int, float)):
        size = mem * MEMORY_UNITS['MB']
    else:
        match = re.fullmatch(r'\s*([\d.]+)\s*([KMGT]?B)\s*', str(mem or ''), re.IGNORECASE)
        if not match:
            return str(mem) if mem else '?'
        size = float(match[1]) * MEMORY_UNITS[match[2].upper()]
    return f'{size / MEMORY_UNITS["GB"]:.1f} GB'


def add_usage_fields(embed: discord.Embed, stats: dict) -> None:
    """
    Add the CPU and RAM usage of a server to the embed.
    """
    embed.add_field(name='CPU', value=f"{stats.get('cpu', '?')}%")
    embed.add_field(name='RAM', value=f"{memory_gb(stats.get('mem'))} ({stats.get('mem_percent', '?')}%)")


def server_stats_embed(server_name: str, stats: dict) -> discord.Embed:
    """
    Build an embed with the stats of one server.
    """
    running = bool(stats.get('running'))
    embed = new_embed(
        title=server_name,
        description='🟢 Online' if running else '🔴 Offline',
        color=COLOR_ONLINE if running else COLOR_OFFLINE,
    )
    embed.add_field(name='World', value=stats.get('world_name') or '-')
    if running:
        embed.add_field(name='Version', value=stats.get('version') or '-')
        embed.add_field(name='Players', value=player_text(stats), inline=False)
        add_usage_fields(embed, stats)
    return embed


def status_embed(entries: list[tuple[dict, dict | None]]) -> discord.Embed:
    """
    Build the status overview embed of all servers.

    Args:
        entries: List of (server, stats) tuples. stats is None if it could not be fetched.
    """
    embed = new_embed(title='Server status', color=COLOR_OFFLINE)
    any_online = False
    for server, stats in entries[:25]:
        name = server.get('server_name', '-')
        if stats is None:
            value = '⚪ Unknown'
        elif stats.get('running'):
            any_online = True
            value = f"🟢 Online · {stats.get('version') or '-'}\nPlayers: {player_text(stats)}"
        else:
            value = '🔴 Offline'
        embed.add_field(name=name, value=value[:MAX_FIELD_LENGTH], inline=False)
    if not entries:
        embed.description = 'No servers found'
        embed.color = COLOR_UNKNOWN
    elif any_online:
        embed.color = COLOR_ONLINE
    embed.set_footer(text=STATUS_FOOTER)
    embed.timestamp = discord.utils.utcnow()
    return embed
