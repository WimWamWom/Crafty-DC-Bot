"""
This module writes the MOTD (the text under the server name in the server list) into server.properties.

A server gets a random message from the list, its own fixed message, or keeps its MOTD.
The server reads server.properties when it starts, so a new MOTD is chosen before every start and restart
by the bot and after every stop the bot sees, which also covers the next start from Crafty.
"""

import json
import os
import random
import re

from core.config import CONFIG_PATH, KEEP_MOTD, get
from core.properties import get_property, read_properties, set_property, write_properties

# &a, &l, ... as an easier way to type § color codes
COLOR_CODE = re.compile(r'&([0-9a-fk-orA-FK-OR])')

# the last random messages per server, so they do not come again too soon
HISTORY_PATH = os.path.join(os.path.dirname(CONFIG_PATH), 'motd_history.json')
# never more than this many remembered per server
MAX_HISTORY = 50


def _load_history() -> dict[str, list[str]]:
    try:
        with open(HISTORY_PATH, encoding='utf-8') as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


history = _load_history()


def _remember(server_id: str, message: str) -> None:
    recent = [entry for entry in history.get(server_id, []) if entry != message] + [message]
    history[server_id] = recent[-MAX_HISTORY:]
    try:
        with open(HISTORY_PATH, 'w', encoding='utf-8') as file:
            json.dump(history, file, ensure_ascii=False)
    except OSError as e:
        print(f'motd: could not save {HISTORY_PATH}: {e}')


def _choice(server_id: str) -> str | None:
    """
    The fixed message of a server, KEEP_MOTD, or None for a random message from the list.
    """
    return get('motd.servers').get(server_id)


def is_active(server_id: str) -> bool:
    if not get('motd.enabled'):
        return False
    choice = _choice(server_id)
    if choice is None:
        return bool(get('motd.messages'))
    return choice != KEEP_MOTD


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
    return set_property(properties, 'motd', value)


def decode(value: str) -> str:
    """
    Undo the escapes of a server.properties value, so values written by us and by Minecraft can be compared.
    """
    value = re.sub(r'\\u([0-9a-fA-F]{4})', lambda match: chr(int(match[1], 16)), value)
    return re.sub(r'\\([=:#!])', r'\1', value)


def current_motd(properties: str) -> str | None:
    value = get_property(properties, 'motd')
    return None if value is None else decode(value)


def apply_motd(properties: str, server_id: str) -> str:
    """
    Put the fixed MOTD of the server, or a random one from the list, into the content of a server.properties file.
    Call only if is_active(server_id).
    """
    fixed = _choice(server_id)
    if fixed is not None:
        return replace_motd(properties, encode(fixed))
    messages = list(dict.fromkeys(get('motd.messages')))
    # skip the current one and the last few, but always leave at least one to choose from
    current = current_motd(properties)
    skip = min(max(get('motd.no_repeat'), 1), len(messages) - 1)
    recent = set(history.get(server_id, [])[-skip:]) if skip else set()
    fresh = [message for message in messages if message not in recent]
    choices = [message for message in fresh if decode(encode(message)) != current] or fresh or messages
    message = random.choice(choices)
    _remember(server_id, message)
    return replace_motd(properties, encode(message))


async def set_motd(server_id: str) -> None:
    """
    Write the fixed MOTD of the server, or a random one from the list, into server.properties of the server.
    Never raises, a failure only means the MOTD stays as it is.
    """
    if not is_active(server_id):
        return
    try:
        read = await read_properties(server_id)
        if read is None:
            return
        path, properties = read
        new_properties = apply_motd(properties, server_id)
        if new_properties != properties and await write_properties(server_id, path, new_properties):
            print(f'motd: new MOTD for {server_id}')
    except Exception as e:
        print(f'motd: failed for {server_id}: {e}')
