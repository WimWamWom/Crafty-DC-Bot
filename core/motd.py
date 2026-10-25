"""
This module writes a random MOTD (the text under the server name in the server list) into server.properties.

The server reads server.properties when it starts, so a new MOTD is chosen before every start and restart
by the bot and after every stop the bot sees, which also covers the next start from Crafty.
"""

import asyncio
import random
import re

from core.config import get
from core.constants import API_ENDPOINT
from core.network import HttpMethod, get_json_response, is_response_successful, send_request

MOTD_ENABLED: bool = get('motd.enabled')
MOTD_MESSAGES: list[str] = get('motd.messages')
MOTD_EXCLUDED: list[str] = get('motd.excluded_servers')

PROPERTIES = 'server.properties'
MOTD_LINE = re.compile(r'\s*motd\s*[=:]')
# &a, &l, ... as an easier way to type § color codes
COLOR_CODE = re.compile(r'&([0-9a-fk-orA-FK-OR])')


def is_active(server_id: str) -> bool:
    return MOTD_ENABLED and bool(MOTD_MESSAGES) and server_id not in MOTD_EXCLUDED


def encode(message: str) -> str:
    """
    Turn a message from the list into a server.properties value.

    & color codes become §, a literal \\n stays the line break of the MOTD,
    and other characters outside ASCII are written as \\uXXXX, which every Minecraft version reads.
    """
    message = COLOR_CODE.sub(lambda match: '§' + match[1].lower(), message)
    return ''.join(char if ord(char) < 128 else f'\\u{ord(char):04x}' for char in message)


def replace_motd(properties: str, value: str) -> str:
    """
    Replace the motd line of a server.properties file, or add one if it has none.
    """
    lines = properties.split('\n')
    for index, line in enumerate(lines):
        if MOTD_LINE.match(line):
            lines[index] = f'motd={value}' + ('\r' if line.endswith('\r') else '')
            return '\n'.join(lines)
    if properties and not properties.endswith('\n'):
        properties += '\n'
    return properties + f'motd={value}\n'


def decode(value: str) -> str:
    """
    Undo the escapes of a server.properties value, so values written by us and by Minecraft can be compared.
    """
    value = re.sub(r'\\u([0-9a-fA-F]{4})', lambda match: chr(int(match[1], 16)), value)
    return re.sub(r'\\([=:#!])', r'\1', value)


def current_motd(properties: str) -> str | None:
    match = re.search(r'^\s*motd\s*[=:]\s*(.*)$', properties, re.MULTILINE)
    return decode(match[1].rstrip('\r')) if match else None


async def _properties_path(server_id: str) -> str | None:
    data = await get_json_response(API_ENDPOINT + server_id, 'motd: failed to get server data')
    path = (data.get('data') or {}).get('path')
    if not path:
        return None
    # Crafty runs on Linux in Docker, older versions only accept absolute paths
    return path.rstrip('/\\') + '/' + PROPERTIES


async def set_random_motd(server_id: str) -> None:
    """
    Write a random MOTD from the list into server.properties of the server.
    Never raises, a failure only means the MOTD stays as it is.
    """
    if not is_active(server_id):
        return
    try:
        path = await _properties_path(server_id)
        if path is None:
            return
        data = await get_json_response(API_ENDPOINT + server_id + '/files', f'motd: failed to read {PROPERTIES}',
                                       method=HttpMethod.POST, data={'path': path})
        properties = (data.get('data') or {}).get('content')
        if properties is None:
            return

        # pick a different one than now if possible
        current = current_motd(properties)
        choices = [message for message in MOTD_MESSAGES if decode(encode(message)) != current] or MOTD_MESSAGES
        new_properties = replace_motd(properties, encode(random.choice(choices)))

        # overwrite skips the check for changes since reading, which older Crafty versions do not know
        url = API_ENDPOINT + server_id + '/files'
        response = await asyncio.to_thread(send_request, url, method=HttpMethod.PATCH,
                                           data={'path': path, 'contents': new_properties, 'overwrite': True})
        if response.status_code == 400:
            response = await asyncio.to_thread(send_request, url, method=HttpMethod.PATCH,
                                               data={'path': path, 'contents': new_properties})
        if is_response_successful(response):
            print(f'motd: new MOTD for {server_id}')
        else:
            print(f'motd: failed to write {PROPERTIES} of {server_id} ({response.status_code}), '
                  f'does the API token have the FILES permission?')
    except Exception as e:
        print(f'motd: failed for {server_id}: {e}')
