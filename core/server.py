"""This module contains functions to query and control Crafty servers."""

import ast

from core.constants import ALLOWED_SERVERS, API_ENDPOINT
from core.network import get_json_response, HttpMethod


async def get_servers(include_all: bool = False) -> list[dict] | None:
    """
    Get the list of servers available in the bot (all servers if include_all is set). Returns None on error.
    """
    data = await get_json_response(API_ENDPOINT, 'failed to get server list')
    if not data or 'data' not in data:
        return None
    if include_all or not ALLOWED_SERVERS:
        return data['data']
    return [server for server in data['data'] if server['server_id'] in ALLOWED_SERVERS]


async def get_server_stats(server_id) -> dict | None:
    """
    Get the stats of the server with the specified ID. Returns None on error.
    """
    data = await get_json_response(API_ENDPOINT + str(server_id) + '/stats',
                                   'failed to get server stats')
    if not data or 'data' not in data:
        return None
    return data['data']


async def server_action(server_id, action: str) -> bool:
    """
    Run an action (e.g. start_server, stop_server, restart_server) on the server with the specified ID.
    """
    data = await get_json_response(API_ENDPOINT + str(server_id) + '/action/' + action,
                                   f'failed to run {action}', method=HttpMethod.POST)
    if data.get('status') == "ok":
        print(action, str(server_id))
        return True
    return False


async def stop_server(server_id) -> bool:
    """
    Stop the server with the specified ID.
    """
    return await server_action(server_id, 'stop_server')


async def get_player_count(server_id) -> int:
    """
    Get the number of players online on the server with the specified server ID.
    Returns -1 on error.
    """
    stats = await get_server_stats(server_id)
    if stats is None:
        return -1
    return stats.get('online', 0)


async def is_server_running(server_id) -> bool | None:
    """
    Check if the server with the specified ID is running. Returns None on error.
    """
    stats = await get_server_stats(server_id)
    if stats is None:
        return None
    return bool(stats.get('running'))


def parse_players(raw) -> list[str]:
    """
    Parse the player list from the server stats.

    Crafty returns the players as the string representation of a Python list, e.g. "['Steve', 'Alex']".
    """
    if isinstance(raw, list):
        return [str(player) for player in raw]
    if not raw or not isinstance(raw, str):
        return []
    try:
        players = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return []
    if isinstance(players, (list, tuple)):
        return [str(player) for player in players]
    return []
