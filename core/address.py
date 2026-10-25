"""
This module gives every started server a domain from a list of domain:port entries.

Each domain points to its port with a Minecraft SRV record, so the domain of a server only depends on the port it
runs on. Before /start, the bot sets the port of the server to the port of the first domain no other running server
uses, writes it into server.properties together with the random MOTD and into the server settings of Crafty, which
uses that port to count the players. Changing the port in Crafty needs the API token of a superuser.
"""

import asyncio
import time

from core.config import KEEP_PORT, get
from core.constants import API_ENDPOINT
from core.motd import apply_random_motd, is_active as motd_active
from core.network import HttpMethod, is_response_successful, send_request
from core.properties import get_property, read_properties, set_property, write_properties
from core.server import get_server_stats, get_servers

ADDRESS_ENABLED: bool = get('address.enabled')
DOMAINS: list[tuple[str, int]] = [(entry.rsplit(':', 1)[0], int(entry.rsplit(':', 1)[1]))
                                  for entry in get('address.domains')]
# server ID -> domain the server always gets, or KEEP_PORT
ADDRESS_FIXED: dict[str, str] = get('address.fixed')

# a port given to a starting server counts as used for this long, until the server shows up as running
RESERVE_TIME = 300

# port -> (server ID, until), so two starts at the same time do not get the same port
_reserved: dict[int, tuple[str, float]] = {}
_lock = asyncio.Lock()


def is_active(server_id: str) -> bool:
    return ADDRESS_ENABLED and bool(DOMAINS) and ADDRESS_FIXED.get(server_id) != KEEP_PORT


def _candidates(server_id: str) -> list[tuple[str, int]]:
    """
    The domains the server may get, in order: only its fixed domain, or all domains not fixed to other servers.
    """
    fixed = ADDRESS_FIXED.get(server_id)
    if fixed and fixed != KEEP_PORT:
        own = [(domain, port) for domain, port in DOMAINS if domain == fixed]
        if own:
            return own
        # the fixed domain was removed from the list: fall back to a free one
    taken = {choice for other, choice in ADDRESS_FIXED.items() if other != server_id}
    return [(domain, port) for domain, port in DOMAINS if domain not in taken]


def domain_for_port(port) -> str | None:
    return next((domain for domain, domain_port in DOMAINS if str(domain_port) == str(port)), None)


def display_address(server: dict) -> str:
    """
    The address shown for a server: its domain if it runs on the port of one, otherwise IP:port.
    """
    port = server.get('server_port', '?')
    return domain_for_port(port) or f"{server.get('server_ip', '?')}:{port}"


async def _used_ports(server_id: str) -> set[int] | None:
    """
    Ports of the other running servers and of servers the bot is starting. None if Crafty can not be reached.
    """
    # servers hidden in the bot run on the same machine and block ports too
    servers = await get_servers(include_all=True)
    if servers is None:
        return None
    others = [server for server in servers if server['server_id'] != server_id]
    stats = await asyncio.gather(*(get_server_stats(server['server_id']) for server in others))
    if any(server_stats is None for server_stats in stats):
        return None
    used = {int(server['server_port']) for server, server_stats in zip(others, stats)
            if server_stats.get('running') and str(server.get('server_port', '')).isdigit()}

    now = time.time()
    for port, (owner, until) in list(_reserved.items()):
        if until < now:
            del _reserved[port]
        elif owner != server_id:
            used.add(port)
    return used


async def has_free_domain(server_id: str) -> bool | None:
    """
    Check if a domain is free for the server. True if the bot does not assign domains to it, None on error.
    """
    if not is_active(server_id):
        return True
    used = await _used_ports(server_id)
    if used is None:
        return None
    return any(port not in used for _, port in _candidates(server_id))


async def _set_crafty_port(server_id: str, port: int) -> bool:
    response = await asyncio.to_thread(send_request, API_ENDPOINT + server_id, method=HttpMethod.PATCH,
                                       data={'server_port': port})
    if is_response_successful(response):
        return True
    print(f'address: failed to set the port of {server_id} in Crafty ({response.status_code}), '
          f'is the API token from a superuser with the CONFIG permission?')
    return False


async def prepare_start(server_id: str) -> tuple[str | None, str | None]:
    """
    Write the port of the first free domain and a random MOTD into server.properties in one go.

    Returns:
        (domain, error): The domain the server gets (None if the bot does not assign one), and why the server
        must not start (None if it may).
    """
    if not is_active(server_id):
        if motd_active(server_id):
            read = await read_properties(server_id)
            if read is not None:
                await write_properties(server_id, read[0], apply_random_motd(read[1]))
        return None, None

    async with _lock:
        used = await _used_ports(server_id)
        if used is None:
            return None, 'failed to check which domains are free'
        candidates = _candidates(server_id)
        free = [(domain, port) for domain, port in candidates if port not in used]
        if not free:
            if len(candidates) == 1 and ADDRESS_FIXED.get(server_id) == candidates[0][0]:
                return None, f'{candidates[0][0]} is used by another server, stop it first'
            return None, 'all domains are in use, stop a server first'
        domain, port = free[0]

        read = await read_properties(server_id)
        if read is None:
            return None, 'failed to read server.properties, does the API token have the FILES permission?'
        path, properties = read

        old_port = get_property(properties, 'server-port')
        server = next((s for s in await get_servers(include_all=True) or [] if s['server_id'] == server_id), {})
        crafty_port = server.get('server_port')
        if str(crafty_port) != str(port) and not await _set_crafty_port(server_id, port):
            return None, 'failed to change the port in Crafty, the API token must be from a superuser'

        new_properties = set_property(properties, 'server-port', str(port))
        if motd_active(server_id):
            new_properties = apply_random_motd(new_properties)
        if new_properties != properties and not await write_properties(server_id, path, new_properties):
            if str(crafty_port) != str(port) and str(crafty_port).isdigit():
                await _set_crafty_port(server_id, int(crafty_port))
            return None, 'failed to write server.properties, does the API token have the FILES permission?'

        _reserved[port] = (server_id, time.time() + RESERVE_TIME)
        if old_port != str(port):
            print(f'address: {server_id} now runs on port {port} ({domain})')
        return domain, None
