"""
This module writes a random MOTD (the text under the server name in the server list) into server.properties.

The server reads server.properties when it starts, so a new MOTD is chosen before every start and restart
by the bot and after every stop the bot sees, which also covers the next start from Crafty.
"""

import random
import re

from core.config import get
from core.properties import get_property, read_properties, set_property, write_properties

# &a, &l, ... as an easier way to type § color codes
COLOR_CODE = re.compile(r'&([0-9a-fk-orA-FK-OR])')


def is_active(server_id: str) -> bool:
    return get('motd.enabled') and bool(get('motd.messages')) and server_id not in get('motd.excluded_servers')


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


def apply_random_motd(properties: str) -> str:
    """
    Put a random MOTD from the list into the content of a server.properties file.
    """
    # pick a different one than now if possible
    current = current_motd(properties)
    messages = get('motd.messages')
    choices = [message for message in messages if decode(encode(message)) != current] or messages
    return replace_motd(properties, encode(random.choice(choices)))


async def set_random_motd(server_id: str) -> None:
    """
    Write a random MOTD from the list into server.properties of the server.
    Never raises, a failure only means the MOTD stays as it is.
    """
    if not is_active(server_id):
        return
    try:
        read = await read_properties(server_id)
        if read is None:
            return
        path, properties = read
        if await write_properties(server_id, path, apply_random_motd(properties)):
            print(f'motd: new MOTD for {server_id}')
    except Exception as e:
        print(f'motd: failed for {server_id}: {e}')
