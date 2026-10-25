"""
This module loads and saves the bot configuration (data/config.yaml).

Values from the config file take precedence. Environment variables are only used
for keys that are missing in the file, so existing Docker/Unraid setups keep working.
On the first start, the config file is created from the environment variables.
"""

import json
import os
from dataclasses import dataclass

import yaml

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CONFIG_PATH = os.environ.get('CONFIG_PATH', os.path.join(ROOT_DIR, 'data', 'config.yaml'))

TRUE_VALUES = ('1', 'true', 'yes', 'on')


@dataclass(frozen=True)
class Field:
    section: str
    key: str
    # str, secret, int, bool, channel, role or servers
    kind: str
    default: object
    env: str | None
    label: str
    help: str
    required: bool = False


SECTIONS = {
    'crafty': 'Crafty Controller',
    'discord': 'Discord',
    'servers': 'Server',
    'auto_stop': 'Auto-Stop',
    'status': 'Status-Embed',
    'web': 'Webinterface',
}

FIELDS = [
    Field('crafty', 'url', 'str', '', 'SERVER_URL', 'Crafty-URL',
          'URL deines Crafty Controllers, z. B. https://crafty.example.de:8443', required=True),
    Field('crafty', 'token', 'secret', '', 'CRAFTY_TOKEN', 'Crafty API-Token',
          'API-Key eines Crafty-Benutzers mit Rechten auf die Server', required=True),
    Field('discord', 'token', 'secret', '', 'DISCORD_TOKEN', 'Discord Bot-Token',
          'Token aus dem Discord Developer Portal', required=True),
    Field('discord', 'guild_id', 'int', 0, 'GUILD_ID', 'Discord-Server-ID',
          'ID deines Discord-Servers (Guild). Ohne sie gibt es keine Slash-Commands'),
    Field('discord', 'command_channel_id', 'channel', 0, 'COMMAND_CHANNEL_ID', 'Befehlskanal',
          'Nur in diesem Kanal reagiert der Bot auf Befehle. 0 = alle Kanäle'),
    Field('discord', 'control_role_id', 'role', 0, 'CONTROL_ROLE_ID', 'Steuer-Rolle',
          'Nur diese Rolle darf Server starten, stoppen und neu starten. 0 = alle'),
    Field('servers', 'allowed', 'servers', [], 'ALLOWED_SERVERS', 'Verfügbare Server',
          'Server-IDs, die im Bot auswählbar sind (auch für Status und Auto-Stop). Leer = alle'),
    Field('auto_stop', 'enabled', 'bool', False, 'ENABLE_AUTO_STOP_SERVER', 'Auto-Stop aktiv',
          'Leere Server automatisch stoppen'),
    Field('auto_stop', 'interval', 'int', 1800, 'AUTO_STOP_SLEEP_TIME', 'Prüfintervall (Sekunden)',
          'Ein Server wird nach zwei Prüfungen ohne Spieler in Folge gestoppt'),
    Field('status', 'channel_id', 'channel', 0, 'STATUS_CHANNEL_ID', 'Status-Kanal',
          'Kanal mit der Statusübersicht, die sich selbst aktualisiert. 0 = aus'),
    Field('status', 'update_interval', 'int', 60, 'STATUS_UPDATE_INTERVAL', 'Aktualisierung (Sekunden)',
          'Wie oft die Statusübersicht aktualisiert wird'),
    Field('web', 'port', 'int', 4883, 'WEB_PORT', 'Port',
          'Port des Webinterfaces. In Docker 4883 lassen und stattdessen das Port-Mapping ändern'),
    Field('web', 'password', 'secret', '', 'WEB_PASSWORD', 'Passwort',
          'Passwort für das Webinterface (Benutzername beliebig). Leer = kein Schutz'),
]

FIELDS_BY_NAME = {f'{field.section}.{field.key}': field for field in FIELDS}


def parse_value(field: Field, raw):
    """
    Convert a raw value (from YAML, environment or web form) to the type of the field.

    Raises:
        ValueError: If the value is invalid.
    """
    if field.kind == 'bool':
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in TRUE_VALUES
    if field.kind in ('int', 'channel', 'role'):
        if raw is None or str(raw).strip() == '':
            return field.default
        value = int(str(raw).strip())
        if value < 0:
            raise ValueError(f'{field.label}: must not be negative')
        return value
    if field.kind == 'servers':
        if raw is None:
            return []
        if isinstance(raw, str):
            raw = raw.split(',')
        return [str(server_id).strip() for server_id in raw if str(server_id).strip()]
    return '' if raw is None else str(raw).strip()


def _from_env(field: Field):
    raw = os.environ.get(field.env) if field.env else None
    if raw is None or raw == '':
        return field.default
    try:
        return parse_value(field, raw)
    except ValueError:
        print(f'Invalid value for {field.env}, using default')
        return field.default


def load() -> dict:
    """
    Load the config file and fill missing keys from the environment or defaults.
    Writes the file if it did not exist or keys were missing.
    """
    file_data = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding='utf-8') as file:
            file_data = yaml.safe_load(file) or {}

    values = {}
    complete = True
    for name, field in FIELDS_BY_NAME.items():
        section = file_data.get(field.section) or {}
        if field.key in section:
            try:
                values[name] = parse_value(field, section[field.key])
                continue
            except ValueError:
                print(f'Invalid value for {name} in {CONFIG_PATH}, using default')
        complete = False
        values[name] = _from_env(field)

    if not complete:
        try:
            save(values)
            print(f'Config written to {CONFIG_PATH}')
        except OSError as e:
            print(f'Could not write config file {CONFIG_PATH}: {e}')
    return values


def render(values: dict) -> str:
    """
    Render the config as YAML with comments.
    """
    lines = ['# Crafty Discord Bot configuration',
             '# Can also be edited in the web interface (default port 4883).',
             '# Changes made here take effect after restarting the bot.']
    for section, title in SECTIONS.items():
        lines += ['', f'# --- {title} ---', f'{section}:']
        for field in FIELDS:
            if field.section != section:
                continue
            lines.append(f'  # {field.help}')
            # JSON is valid YAML and quotes strings safely
            lines.append(f'  {field.key}: {json.dumps(values[f"{section}.{field.key}"], ensure_ascii=False)}')
    return '\n'.join(lines) + '\n'


def save(values: dict) -> None:
    """
    Write the config file atomically.
    """
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp_path = CONFIG_PATH + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as file:
        file.write(render(values))
    os.replace(tmp_path, CONFIG_PATH)


def missing_required(values: dict) -> list[str]:
    """
    Return the labels of required fields that are not set.
    """
    return [field.label for name, field in FIELDS_BY_NAME.items() if field.required and not values[name]]


config = load()


def get(name: str):
    """
    Get a config value by name, e.g. get('crafty.url').
    """
    return config[name]
