"""
This module loads and saves the bot configuration (data/config.yaml).

Values from the config file take precedence. Environment variables are only used
for keys that are missing in the file, so existing Docker/Unraid setups keep working.
On the first start, the config file is created from the environment variables.
"""

import json
import os
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import yaml

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CONFIG_PATH = os.environ.get('CONFIG_PATH', os.path.join(ROOT_DIR, 'data', 'config.yaml'))

TRUE_VALUES = ('1', 'true', 'yes', 'on')


@dataclass(frozen=True)
class Field:
    section: str
    key: str
    # str, secret, int, bool, channel, role, servers, list, lines, time, weekday or timezone
    kind: str
    default: object
    env: str | None
    label: str
    help: str
    required: bool = False
    # longer hints shown in a collapsible box in the web interface, one per line
    details: str = ''


SECTIONS = {
    'crafty': 'Crafty Controller',
    'discord': 'Discord',
    'servers': 'Server',
    'auto_stop': 'Auto-Stop',
    'status': 'Status-Embed',
    'session': 'Start & Stopp',
    'backup': 'Backups',
    'motd': 'MOTD',
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
    Field('discord', 'command_channel_enabled', 'bool', False, 'COMMAND_CHANNEL_ENABLED',
          'Befehle nur in einem Kanal', 'Aus = der Bot reagiert in allen Kanälen'),
    Field('discord', 'command_channel_id', 'channel', 0, 'COMMAND_CHANNEL_ID', 'Befehlskanal',
          'Nur in diesem Kanal reagiert der Bot auf Befehle'),
    Field('discord', 'control_role_enabled', 'bool', False, 'CONTROL_ROLE_ENABLED',
          'Steuern nur mit Rolle', 'Aus = jeder darf Server starten, stoppen und neu starten'),
    Field('discord', 'control_role_id', 'role', 0, 'CONTROL_ROLE_ID', 'Steuer-Rolle',
          'Nur diese Rolle darf Server starten, stoppen und neu starten'),
    Field('servers', 'allowed', 'servers', [], 'ALLOWED_SERVERS', 'Verfügbare Server',
          'Server-IDs, die im Bot auswählbar sind (auch für Status und Auto-Stop). Leer = alle'),
    Field('auto_stop', 'enabled', 'bool', False, 'ENABLE_AUTO_STOP_SERVER', 'Auto-Stop aktiv',
          'Leere Server automatisch stoppen'),
    Field('auto_stop', 'idle_minutes', 'int', 120, 'AUTO_STOP_IDLE_MINUTES', 'Wartezeit (Minuten)',
          'So lange nachdem der letzte Spieler gegangen ist (oder nach dem Start, wenn niemand kommt) '
          'wird der Server gestoppt. Kommt vorher jemand, beginnt die Zeit beim nächsten Verlassen neu'),
    Field('status', 'enabled', 'bool', False, 'STATUS_ENABLED', 'Statusübersicht aktiv',
          'Statusübersicht im Status-Kanal anzeigen'),
    Field('status', 'channel_id', 'channel', 0, 'STATUS_CHANNEL_ID', 'Status-Kanal',
          'Kanal mit der Statusübersicht, die sich selbst aktualisiert'),
    Field('status', 'update_interval', 'int', 60, 'STATUS_UPDATE_INTERVAL', 'Aktualisierung (Sekunden)',
          'Wie oft die Statusübersicht aktualisiert wird'),
    Field('session', 'enabled', 'bool', True, 'SESSION_ENABLED', 'Embed bei jedem Serverstart',
          'Bei /start antwortet der Bot mit einem Embed, das „Backup wird erstellt“, dann den laufenden Server '
          'mit Spielern und der Zeit bis zum Auto-Stop und am Ende Grund und Laufzeit des Stopps zeigt. '
          'Es bleibt danach im Kanal stehen und ersetzt die Start/Stop-Webhooks von Crafty'),
    Field('session', 'channel_id', 'channel', 0, 'SESSION_CHANNEL_ID', 'Kanal für Start/Stopp-Nachrichten',
          'Alle Embeds erscheinen hier, auch für Server, die außerhalb des Bots gestartet wurden (z. B. in Crafty). '
          'Leer = im Kanal von /start, Starts außerhalb des Bots im Befehlskanal'),
    Field('backup', 'enabled', 'bool', False, None, 'Automatische Backups aktiv',
          'Der Bot legt bei jedem verfügbaren Server die Backup-Konfigurationen „Bot Start“, „Bot Täglich“ '
          'und „Bot Wöchentlich“ in Crafty an und hält sie aktuell. Backups werden nur erstellt, '
          'wenn der Server seit dem letzten Backup dieser Art online war'),
    Field('backup', 'excluded_servers', 'servers', [], None, 'Server ohne Backups',
          'Für diese Server erstellt der Bot keine Backups. Ihre bisherigen Bot-Backups bleiben, '
          'außer die Option darunter ist an'),
    Field('backup', 'delete_excluded', 'bool', False, None, 'Bot-Backups dieser Server löschen',
          'Löscht alle Backups von „Bot Start“, „Bot Täglich“ und „Bot Wöchentlich“ der Server oben. '
          'Die Welt selbst und Backups, die du in Crafty angelegt hast, bleiben. Kann nicht rückgängig gemacht werden'),
    Field('backup', 'delete_after_days', 'int', 0, None, 'Bot-Backups inaktiver Server löschen nach (Tagen)',
          'War ein Server so viele Tage nicht online, löscht der Bot alle seine Bot-Backups, '
          'weil nur noch die aktuelle Welt gebraucht wird. Beim nächsten Start gibt es wieder ein Backup. '
          'Die Welt selbst und Backups, die du in Crafty angelegt hast, bleiben. 0 = aus'),
    Field('backup', 'on_start', 'int', 5, None, 'Backups vor dem Start (Anzahl)',
          'Vor /start wird ein Backup erstellt, der Server startet erst danach. '
          'So viele werden behalten, ältere löscht Crafty. 0 = aus'),
    Field('backup', 'daily', 'int', 7, None, 'Tägliche Backups (Anzahl)',
          'So viele tägliche Backups werden behalten. 0 = aus'),
    Field('backup', 'weekly', 'int', 4, None, 'Wöchentliche Backups (Anzahl)',
          'So viele wöchentliche Backups werden behalten. 0 = aus'),
    Field('backup', 'time', 'time', '04:00', None, 'Uhrzeit',
          'Zu dieser Uhrzeit laufen die täglichen und wöchentlichen Backups. War der Bot zu der Zeit aus, '
          'holt er sie beim nächsten Start nach'),
    Field('backup', 'weekday', 'weekday', 6, None, 'Wochentag für wöchentliche Backups',
          'An diesem Tag läuft zusätzlich zum täglichen das wöchentliche Backup'),
    Field('backup', 'timezone', 'timezone', 'Europe/Berlin', 'TZ', 'Zeitzone',
          'Zeitzone für die Uhrzeit, z. B. Europe/Berlin'),
    Field('backup', 'compress', 'bool', True, None, 'Komprimieren',
          'Backups als komprimiertes ZIP speichern. Spart meist 30–50 % Platz, dauert etwas länger'),
    Field('backup', 'excluded_dirs', 'list', ['logs', 'crash-reports', 'cache', 'debug'], None,
          'Ausgeschlossene Ordner',
          'Ein Ordner pro Zeile, relativ zum Serverordner, z. B. logs oder plugins/dynmap/web/tiles',
          details='Kann sicher weg (wird neu erzeugt oder ist nur zur Fehlersuche):\n'
                  'logs, crash-reports, debug – Logdateien und Absturzberichte\n'
                  'cache – Download-Cache von Paper/Spigot\n'
                  'bluemap/web/maps oder plugins/BlueMap/web/maps – gerenderte BlueMap-Karten\n'
                  'dynmap/web/tiles oder plugins/dynmap/web/tiles – gerenderte Dynmap-Karten\n'
                  'plugins/squaremap/web/tiles – gerenderte squaremap-Karten\n'
                  'Nur ausschließen, wenn du sie neu herunterladen kannst:\n'
                  'libraries, versions, .fabric – Serverdateien des Loaders (Forge/Fabric), '
                  'nach einer Wiederherstellung ggf. Installer erneut ausführen\n'
                  'Nie ausschließen:\n'
                  'world, world_nether, world_the_end (bzw. dein level-name) – die Welt selbst\n'
                  'mods, plugins, config, defaultconfigs, kubejs – Mods, Plugins und ihre Einstellungen\n'
                  'server.properties, ops.json, whitelist.json und andere Dateien im Hauptordner'),
    Field('backup', 'before_command', 'str', 'save-off', None, 'Befehl vor dem Backup',
          'Wird an laufende Server gesendet, damit die Welt während des Backups nicht geschrieben wird. Leer = keiner'),
    Field('backup', 'after_command', 'str', 'save-on', None, 'Befehl nach dem Backup',
          'Wird nach dem Backup an laufende Server gesendet. Leer = keiner'),
    Field('backup', 'timeout', 'int', 600, None, 'Maximale Wartezeit beim Start (Sekunden)',
          'So lange wartet /start auf das Backup. Danach startet der Server trotzdem'),
    Field('motd', 'enabled', 'bool', False, None, 'Zufällige MOTD aktiv',
          'Vor jedem Start und Neustart durch den Bot und nach jedem Stopp schreibt der Bot eine zufällige '
          'Nachricht aus der Liste als motd in die server.properties. Sie wechselt also pro Serverstart, '
          'nicht bei jedem Neuladen der Serverliste. Der API-Token braucht dafür das Recht FILES'),
    Field('motd', 'messages', 'lines', [], None, 'Nachrichten',
          'Eine Nachricht pro Zeile. \\n im Text = zweite Zeile, &a, &l usw. = Farben und Formatierung',
          details='Farben:\n'
                  '&0 Schwarz, &1 Dunkelblau, &2 Dunkelgrün, &3 Türkis, &4 Dunkelrot, &5 Lila, &6 Gold, &7 Grau\n'
                  '&8 Dunkelgrau, &9 Blau, &a Grün, &b Hellblau, &c Rot, &d Pink, &e Gelb, &f Weiß\n'
                  'Formatierung:\n'
                  '&l fett, &o kursiv, &n unterstrichen, &m durchgestrichen, &k verschlüsselt, &r zurücksetzen\n'
                  'Beispiel:\n'
                  '&6&lWimWamWom &7| &aHeute mit Creeper-Garantie\\n&eKomm vorbei!'),
    Field('motd', 'excluded_servers', 'servers', [], None, 'Server ohne zufällige MOTD',
          'Bei diesen Servern lässt der Bot die motd in der server.properties unverändert'),
    Field('web', 'port', 'int', 4883, 'WEB_PORT', 'Port',
          'Port des Webinterfaces. In Docker 4883 lassen und stattdessen das Port-Mapping ändern'),
    Field('web', 'password', 'secret', '', 'WEB_PASSWORD', 'Passwort',
          'Passwort für das Webinterface (Benutzername beliebig). Leer = kein Schutz'),
]

FIELDS_BY_NAME = {f'{field.section}.{field.key}': field for field in FIELDS}

# On/off switches and the setting they enable. The selected ID is kept while switched off.
TOGGLES = {
    'discord.command_channel_enabled': 'discord.command_channel_id',
    'discord.control_role_enabled': 'discord.control_role_id',
    'status.enabled': 'status.channel_id',
}
TOGGLED_BY = {target: toggle for toggle, target in TOGGLES.items()}


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
    if field.kind == 'time':
        match = re.fullmatch(r'(\d{1,2}):(\d{2})', str(raw or '').strip())
        if not match or int(match[1]) > 23 or int(match[2]) > 59:
            raise ValueError(f'{field.label}: expected HH:MM')
        return f'{int(match[1]):02d}:{match[2]}'
    if field.kind == 'weekday':
        value = int(str(raw).strip())
        if not 0 <= value <= 6:
            raise ValueError(f'{field.label}: expected 0 (Monday) to 6 (Sunday)')
        return value
    if field.kind == 'timezone':
        value = str(raw or '').strip()
        try:
            ZoneInfo(value)
        except (ValueError, KeyError):
            raise ValueError(f'{field.label}: unknown timezone') from None
        return value
    if field.kind == 'list':
        if raw is None:
            return []
        if isinstance(raw, str):
            raw = raw.splitlines()
        return [str(item).strip().strip('/') for item in raw if str(item).strip().strip('/')]
    if field.kind == 'lines':
        if raw is None:
            return []
        if isinstance(raw, str):
            raw = raw.splitlines()
        return [str(item).strip() for item in raw if str(item).strip()]
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
    missing = []
    for name, field in FIELDS_BY_NAME.items():
        section = file_data.get(field.section) or {}
        if field.key in section:
            try:
                values[name] = parse_value(field, section[field.key])
                continue
            except ValueError:
                print(f'Invalid value for {name} in {CONFIG_PATH}, using default')
        missing.append(name)
        values[name] = _from_env(field)

    # Older configs have no switches: switch on what already has an ID
    for toggle, target in TOGGLES.items():
        if toggle in missing and not os.environ.get(FIELDS_BY_NAME[toggle].env):
            values[toggle] = bool(values[target])

    if missing:
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


def enabled_value(name: str):
    """
    Get a setting that has an on/off switch, or 0 if it is switched off.
    """
    return config[name] if config[TOGGLED_BY[name]] else 0


config = load()


def get(name: str):
    """
    Get a config value by name, e.g. get('crafty.url').
    """
    return config[name]
