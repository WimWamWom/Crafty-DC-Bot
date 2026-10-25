"""
This module keeps a server icon (the picture next to the server in the server list) per server.

Icons are uploaded in the web interface, stored as 64x64 PNG next to the config file and written as
server-icon.png into the server folder through the Crafty upload API. Minecraft only shows icons of exactly
64x64 pixels and reads the file when the server starts, so the icon is written before every start and restart
by the bot and after every stop the bot sees, which also covers the next start from Crafty.
"""

import asyncio
import base64
import binascii
import io
import os
import re
import time
import uuid

from PIL import Image, ImageOps

from core.config import CONFIG_PATH
from core.constants import API_ENDPOINT
from core.network import get_json_response, is_response_successful, send_request, upload_file
from core.server import get_server_stats

ICON_DIR = os.path.join(os.path.dirname(CONFIG_PATH), 'icons')
ICON_FILE = 'server-icon.png'
ICON_SIZE = 64
# larger uploads are refused before they are opened
MAX_UPLOAD = 10 * 1024 * 1024
SERVER_ID = re.compile(r'[a-z0-9-]+')
PNG_SIGNATURE = b'\x89PNG'
# icons read from the servers, kept for a minute so the web interface does not ask Crafty on every view
CACHE_TIME = 60
_current: dict[str, tuple[float, bytes | None]] = {}


def icon_path(server_id: str) -> str:
    if not SERVER_ID.fullmatch(server_id):
        raise ValueError('invalid server ID')
    return os.path.join(ICON_DIR, f'{server_id}.png')


def has_icon(server_id: str) -> bool:
    return os.path.isfile(icon_path(server_id))


def to_icon(data: bytes) -> bytes:
    """
    Turn any picture into a 64x64 PNG: cut to a square in the middle, then scaled.

    Raises:
        ValueError: If the data is not a picture.
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image).convert('RGBA')
            image = ImageOps.fit(image, (ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
    except (OSError, Image.DecompressionBombError) as e:
        raise ValueError(f'not a picture: {e}') from None
    output = io.BytesIO()
    image.save(output, 'PNG', optimize=True)
    return output.getvalue()


def save_icon(server_id: str, data: bytes) -> None:
    """
    Store an uploaded picture as the icon of the server.

    Raises:
        ValueError: If the upload is too large or not a picture.
    """
    if len(data) > MAX_UPLOAD:
        raise ValueError('picture too large')
    icon = to_icon(data)
    os.makedirs(ICON_DIR, exist_ok=True)
    with open(icon_path(server_id), 'wb') as file:
        file.write(icon)


def delete_icon(server_id: str) -> None:
    if has_icon(server_id):
        os.remove(icon_path(server_id))


async def set_icon(server_id: str) -> None:
    """
    Write the icon of the server as server-icon.png into its folder, if it has one.
    Never raises, a failure only means the icon stays as it is.
    """
    try:
        if not has_icon(server_id):
            return
        with open(icon_path(server_id), 'rb') as file:
            icon = file.read()
        data = await get_json_response(API_ENDPOINT + server_id, f'failed to get server data of {server_id}')
        path = (data.get('data') or {}).get('path')
        if not path:
            return
        # no chunked header: Crafty writes the body as the whole file
        headers = {'fileName': ICON_FILE, 'location': path, 'fileId': str(uuid.uuid4()),
                   'fileSize': str(len(icon)), 'totalChunks': '1'}
        response = await asyncio.to_thread(upload_file, API_ENDPOINT + server_id + '/files/upload/', icon, headers)
        if is_response_successful(response):
            _current.pop(server_id, None)
            print(f'icon: wrote {ICON_FILE} for {server_id}')
        else:
            print(f'icon: failed to write {ICON_FILE} for {server_id} ({response.status_code}), '
                  f'does the API token have the FILES permission?')
    except Exception as e:
        print(f'icon: failed for {server_id}: {e}')


def _read_current(server_id: str) -> bytes | None:
    response = send_request(API_ENDPOINT + server_id + '/files/' + ICON_FILE + '/download', timeout=10)
    if is_response_successful(response) and response.content.startswith(PNG_SIGNATURE):
        return response.content
    return None


async def current_icon(server_id: str) -> bytes | None:
    """
    The icon the server shows now: its server-icon.png, or the icon from Crafty's last ping if older Crafty versions
    can not download files. None if it has none.
    """
    cached = _current.get(server_id)
    if cached and time.time() - cached[0] < CACHE_TIME:
        return cached[1]
    data = None
    try:
        data = await asyncio.to_thread(_read_current, server_id)
        if data is None:
            stats = await get_server_stats(server_id) or {}
            if stats.get('icon'):
                # may come as a data URL from the Minecraft ping
                data = base64.b64decode(str(stats['icon']).split(',')[-1])
                if not data.startswith(PNG_SIGNATURE):
                    data = None
    except (binascii.Error, ValueError, OSError) as e:
        print(f'icon: failed to read the icon of {server_id}: {e}')
    _current[server_id] = (time.time(), data)
    return data
