"""
This module builds the Discord embeds for the server information.
"""

import discord

from core.server import parse_players

COLOR_ONLINE = discord.Color.green()
COLOR_OFFLINE = discord.Color.red()
COLOR_UNKNOWN = discord.Color.light_grey()

# Footer text used to find the status message again after a restart
STATUS_FOOTER = 'Crafty server status'

# Discord limits embed field values to 1024 characters
MAX_FIELD_LENGTH = 1024


def _player_text(stats: dict) -> str:
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


def server_list_embed(servers: list[dict]) -> discord.Embed:
    """
    Build an embed with all servers and their ID, IP and port.
    """
    embed = discord.Embed(title='Servers', color=discord.Color.blurple())
    for server in servers[:25]:
        embed.add_field(
            name=server.get('server_name', '-'),
            value=(f"ID: `{server.get('server_id', '-')}`\n"
                   f"Address: `{server.get('server_ip', 'unknown')}:{server.get('server_port', 'unknown')}`"),
            inline=False,
        )
    if not servers:
        embed.description = 'No servers found'
    return embed


def server_stats_embed(server_name: str, stats: dict) -> discord.Embed:
    """
    Build an embed with the stats of one server.
    """
    running = bool(stats.get('running'))
    embed = discord.Embed(
        title=server_name,
        description='🟢 Online' if running else '🔴 Offline',
        color=COLOR_ONLINE if running else COLOR_OFFLINE,
    )
    embed.add_field(name='World', value=stats.get('world_name') or '-')
    if running:
        embed.add_field(name='Version', value=stats.get('version') or '-')
        embed.add_field(name='Players', value=_player_text(stats), inline=False)
        embed.add_field(name='CPU', value=f"{stats.get('cpu', '?')}%")
        mem = stats.get('mem', '?')
        if isinstance(mem, (int, float)):
            mem = f'{mem} MB'
        embed.add_field(name='RAM', value=f"{mem} ({stats.get('mem_percent', '?')}%)")
    return embed


def status_embed(entries: list[tuple[dict, dict | None]]) -> discord.Embed:
    """
    Build the status overview embed of all servers.

    Args:
        entries: List of (server, stats) tuples. stats is None if it could not be fetched.
    """
    embed = discord.Embed(title='Server status', color=COLOR_OFFLINE)
    any_online = False
    for server, stats in entries[:25]:
        name = server.get('server_name', '-')
        if stats is None:
            value = '⚪ Unknown'
        elif stats.get('running'):
            any_online = True
            value = f"🟢 Online · {stats.get('version') or '-'}\nPlayers: {_player_text(stats)}"
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
