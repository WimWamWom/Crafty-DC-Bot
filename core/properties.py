"""
This module reads and writes server.properties of a Crafty server through the Crafty files API.

The API token needs the FILES permission.
"""

import asyncio
import re

from core.constants import API_ENDPOINT
from core.network import HttpMethod, get_json_response, is_response_successful, send_request

PROPERTIES = 'server.properties'


async def properties_path(server_id: str) -> str | None:
    data = await get_json_response(API_ENDPOINT + server_id, f'failed to get server data of {server_id}')
    path = (data.get('data') or {}).get('path')
    if not path:
        return None
    # Crafty runs on Linux in Docker, older versions only accept absolute paths
    return path.rstrip('/\\') + '/' + PROPERTIES


async def read_properties(server_id: str) -> tuple[str, str] | None:
    """
    Read server.properties of the server. Returns (path, content) or None on error.
    """
    path = await properties_path(server_id)
    if path is None:
        return None
    data = await get_json_response(API_ENDPOINT + server_id + '/files', f'failed to read {PROPERTIES} of {server_id}',
                                   method=HttpMethod.POST, data={'path': path})
    content = (data.get('data') or {}).get('content')
    if content is None:
        return None
    return path, content


async def write_properties(server_id: str, path: str, content: str) -> bool:
    """
    Overwrite server.properties of the server.
    """
    # overwrite skips the check for changes since reading, which older Crafty versions do not know
    url = API_ENDPOINT + server_id + '/files'
    response = await asyncio.to_thread(send_request, url, method=HttpMethod.PATCH,
                                       data={'path': path, 'contents': content, 'overwrite': True})
    if response.status_code == 400:
        response = await asyncio.to_thread(send_request, url, method=HttpMethod.PATCH,
                                           data={'path': path, 'contents': content})
    if is_response_successful(response):
        return True
    print(f'failed to write {PROPERTIES} of {server_id} ({response.status_code}), '
          f'does the API token have the FILES permission?')
    return False


def _key_pattern(key: str) -> re.Pattern:
    return re.compile(r'\s*' + re.escape(key) + r'\s*[=:]')


def set_property(properties: str, key: str, value: str) -> str:
    """
    Replace the line of a key in a server.properties file, or add one if it has none.
    """
    pattern = _key_pattern(key)
    lines = properties.split('\n')
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index] = f'{key}={value}' + ('\r' if line.endswith('\r') else '')
            return '\n'.join(lines)
    if properties and not properties.endswith('\n'):
        properties += '\n'
    return properties + f'{key}={value}\n'


def get_property(properties: str, key: str) -> str | None:
    match = re.search(r'^\s*' + re.escape(key) + r'\s*[=:]\s*(.*)$', properties, re.MULTILINE)
    return match[1].rstrip('\r') if match else None
