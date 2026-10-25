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

# address.fixed value for servers whose port the bot does not change
KEEP_PORT = 'keep'


@dataclass(frozen=True)
class Field:
    section: str
    key: str
    # str, secret, int, bool, channel, role, servers, list, lines, domains, server_domains, time, weekday or timezone
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
    'address': 'Domains',
    'backup': 'Backups',
    'motd': 'MOTD',
    'web': 'Webinterface',
}

FIELDS = [
    Field('crafty', 'url', 'str', '', 'SERVER_URL', 'Crafty-URL',
          'Adresse deines Crafty Controllers, z. B. https://crafty.example.de:8443', required=True),
    Field('crafty', 'token', 'secret', '', 'CRAFTY_TOKEN', 'Crafty API-Token',
          'In Crafty beim Benutzer des Bots unter „API Key“ erstellen. Rechte: COMMANDS, TERMINAL, PLAYERS, '
          'dazu BACKUP für Backups, FILES für MOTD und Domains. Für Domains muss es ein Superuser mit CONFIG sein',
          required=True),
    Field('discord', 'token', 'secret', '', 'DISCORD_TOKEN', 'Discord Bot-Token',
          'Im Discord Developer Portal: deine Anwendung → Bot → Reset Token', required=True),
    Field('discord', 'guild_id', 'int', 0, 'GUILD_ID', 'Discord-Server-ID',
          'Rechtsklick auf deinen Discord-Server → „Server-ID kopieren“ (dafür in Discord den Entwicklermodus '
          'einschalten). Ohne ID gibt es keine Slash-Befehle'),
    Field('discord', 'command_channel_enabled', 'bool', False, 'COMMAND_CHANNEL_ENABLED',
          'Befehle nur in einem Kanal', 'Aus = Befehle funktionieren in allen Kanälen'),
    Field('discord', 'command_channel_id', 'channel', 0, 'COMMAND_CHANNEL_ID', 'Befehlskanal',
          'Nur hier reagiert der Bot auf Befehle'),
    Field('discord', 'control_role_enabled', 'bool', False, 'CONTROL_ROLE_ENABLED',
          'Steuern nur mit Rolle', 'Aus = jeder darf /start, /stop und /restart benutzen'),
    Field('discord', 'control_role_id', 'role', 0, 'CONTROL_ROLE_ID', 'Steuer-Rolle',
          'Nur Mitglieder mit dieser Rolle dürfen /start, /stop und /restart benutzen'),
    Field('servers', 'allowed', 'servers', [], 'ALLOWED_SERVERS', 'Verfügbare Server',
          'Nur diese Server zeigt und steuert der Bot (Befehle, Status, Auto-Stop, Backups). Nichts ausgewählt = alle'),
    Field('auto_stop', 'enabled', 'bool', False, 'ENABLE_AUTO_STOP_SERVER', 'Auto-Stop aktiv',
          'Server stoppen, wenn eine Weile niemand online war'),
    Field('auto_stop', 'idle_minutes', 'int', 120, 'AUTO_STOP_IDLE_MINUTES', 'Wartezeit (Minuten)',
          'So viele Minuten ohne Spieler, dann wird gestoppt. Die Zeit läuft ab dem Moment, in dem der letzte '
          'Spieler geht, oder ab dem Start, wenn niemand kommt'),
    Field('status', 'enabled', 'bool', False, 'STATUS_ENABLED', 'Statusübersicht aktiv',
          'Eine Nachricht mit allen Servern, die sich selbst aktualisiert'),
    Field('status', 'channel_id', 'channel', 0, 'STATUS_CHANNEL_ID', 'Status-Kanal',
          'In diesem Kanal steht die Statusübersicht'),
    Field('status', 'update_interval', 'int', 60, 'STATUS_UPDATE_INTERVAL', 'Aktualisierung (Sekunden)',
          'Wie oft die Statusübersicht neu geladen wird'),
    Field('session', 'enabled', 'bool', True, 'SESSION_ENABLED', 'Nachricht bei jedem Serverstart',
          'Der Bot schreibt bei jedem Start eine Nachricht, die mitläuft: Backup, Start, online mit Spielern, '
          'CPU/RAM und Auto-Stop-Countdown, am Ende gestoppt mit Grund und Laufzeit. '
          'Ersetzt die Start/Stopp-Webhooks von Crafty'),
    Field('session', 'channel_id', 'channel', 0, 'SESSION_CHANNEL_ID', 'Kanal für Start/Stopp-Nachrichten',
          'Hier erscheinen alle diese Nachrichten, auch für Starts direkt in Crafty. Leer = im Kanal von /start, '
          'Starts in Crafty dann im Befehlskanal'),
    Field('address', 'enabled', 'bool', False, None, 'Erste freie Domain automatisch vergeben',
          'Vor jedem /start bekommt der Server den Port der ersten Domain aus der Liste, die gerade frei ist. '
          'Ist keine frei, startet er nicht. Braucht einen Superuser-Token mit CONFIG und FILES'),
    Field('address', 'domains', 'domains', [], None, 'Domains',
          'Eine pro Zeile als domain:port, z. B. mc1.example.de:25566. Die obere wird zuerst vergeben. '
          'Läuft ein Server auf einem dieser Ports, zeigt das Start-Embed die Domain statt IP:Port',
          details='Pro Domain in Cloudflare (nur DNS, graue Wolke):\n'
                  'Ein A-Eintrag (oder DDNS) für den Host, z. B. mc.example.de, den alle Domains als Ziel nutzen\n'
                  'Ein SRV-Eintrag _minecraft._tcp.<name> mit Priorität 0, Gewicht 5, dem Port und dem Host als Ziel\n'
                  'Beispiel:\n'
                  '_minecraft._tcp.mc1.example.de SRV 0 5 25566 mc.example.de\n'
                  'Im Router:\n'
                  'Jeden Port der Liste (TCP) an den Rechner mit Crafty weiterleiten'),
    Field('address', 'fixed', 'server_domains', {}, None, 'Domain pro Server',
          'Automatisch = erste freie Domain. Eine feste Domain gehört immer diesem Server und wird keinem anderen '
          'gegeben. „Port nicht ändern“ = der Bot lässt den Port des Servers, wie er ist'),
    Field('backup', 'enabled', 'bool', False, None, 'Automatische Backups aktiv',
          'Der Bot legt in Crafty die Backups „Bot Start“, „Bot Täglich“ und „Bot Wöchentlich“ an. '
          'Gesichert wird nur, wenn der Server seit dem letzten Backup an war'),
    Field('backup', 'excluded_servers', 'servers', [], None, 'Server ohne Backups',
          'Für diese Server macht der Bot keine Backups'),
    Field('backup', 'delete_excluded', 'bool', False, None, 'Bot-Backups dieser Server löschen',
          'Löscht die Bot-Backups der Server oben. Die Welt und deine eigenen Crafty-Backups bleiben. '
          'Nicht rückgängig zu machen'),
    Field('backup', 'delete_after_days', 'int', 0, None, 'Bot-Backups löschen nach (Tagen aus)',
          'War ein Server so viele Tage aus, löscht der Bot seine Bot-Backups. Die Welt und deine eigenen '
          'Crafty-Backups bleiben, beim nächsten Start gibt es wieder ein Backup. 0 = nie'),
    Field('backup', 'on_start', 'int', 5, None, 'Backups vor dem Start (Anzahl)',
          'Vor jedem /start wird erst gesichert, dann gestartet. So viele bleiben, ältere werden gelöscht. 0 = aus'),
    Field('backup', 'daily', 'int', 7, None, 'Tägliche Backups (Anzahl)',
          'So viele tägliche Backups bleiben. 0 = aus'),
    Field('backup', 'weekly', 'int', 4, None, 'Wöchentliche Backups (Anzahl)',
          'So viele wöchentliche Backups bleiben. 0 = aus'),
    Field('backup', 'time', 'time', '04:00', None, 'Uhrzeit',
          'Zu dieser Zeit laufen die täglichen und wöchentlichen Backups. War der Bot aus, holt er sie nach'),
    Field('backup', 'weekday', 'weekday', 6, None, 'Wochentag für wöchentliche Backups',
          'An diesem Tag läuft zusätzlich zum täglichen das wöchentliche Backup'),
    Field('backup', 'timezone', 'timezone', 'Europe/Berlin', 'TZ', 'Zeitzone',
          'Für die Uhrzeit oben, z. B. Europe/Berlin'),
    Field('backup', 'compress', 'bool', True, None, 'Komprimieren',
          'Spart meist 30–50 % Platz, dauert etwas länger'),
    Field('backup', 'excluded_dirs', 'list', ['logs', 'crash-reports', 'cache', 'debug'], None,
          'Ausgeschlossene Ordner',
          'Diese Ordner kommen nicht ins Backup. Einer pro Zeile, vom Serverordner aus, z. B. logs',
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
          'Geht an laufende Server, bevor gesichert wird. save-off = Welt solange nicht speichern. Leer = keiner'),
    Field('backup', 'after_command', 'str', 'save-on', None, 'Befehl nach dem Backup',
          'Geht danach an laufende Server. save-on = Speichern wieder an. Leer = keiner'),
    Field('backup', 'timeout', 'int', 600, None, 'Höchstens warten auf Start-Backup (Sekunden)',
          'Dauert das Backup vor /start länger, startet der Server trotzdem'),
    Field('motd', 'enabled', 'bool', False, None, 'Zufällige MOTD aktiv',
          'Die MOTD ist der Text unter dem Servernamen in der Serverliste. Bei jedem Start setzt der Bot eine '
          'zufällige Nachricht aus der Liste. Braucht das Recht FILES'),
    Field('motd', 'messages', 'lines', [], None, 'Nachrichten',
          'Eine Nachricht pro Zeile. Farben und Formatierung mit &-Codes (siehe Hinweise), zweite Zeile mit \\n. '
          'Unten siehst du die Vorschau'),
    Field('motd', 'excluded_servers', 'servers', [], None, 'Server ohne zufällige MOTD',
          'Diese Server behalten ihre MOTD'),
    Field('web', 'port', 'int', 4883, 'WEB_PORT', 'Port',
          'In Docker 4883 lassen und nur das Port-Mapping ändern'),
    Field('web', 'password', 'secret', '', 'WEB_PASSWORD', 'Passwort',
          'Schützt das Webinterface (Benutzername egal). Leer = kein Passwort'),
]

FIELDS_BY_NAME = {f'{field.section}.{field.key}': field for field in FIELDS}

# Settings that only take effect after a restart: the Discord login, the guild the slash commands are registered
# for and the port of the web interface. Everything else is read on every use.
RESTART_FIELDS = {'discord.token', 'discord.guild_id', 'web.port'}

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
    if field.kind == 'domains':
        if raw is None:
            return []
        if isinstance(raw, str):
            raw = raw.splitlines()
        domains, ports = [], set()
        for item in raw:
            line = str(item).strip()
            if not line:
                continue
            match = re.fullmatch(r'([A-Za-z0-9.-]+):(\d{1,5})', line)
            if not match or not 0 < int(match[2]) < 65536:
                raise ValueError(f'{field.label}: expected domain:port, got {line}')
            if int(match[2]) in ports:
                raise ValueError(f'{field.label}: port {match[2]} is used twice')
            ports.add(int(match[2]))
            domains.append(f'{match[1].lower()}:{int(match[2])}')
        return domains
    if field.kind == 'server_domains':
        # server ID -> domain or KEEP_PORT; servers without an entry get the first free domain
        if not raw:
            return {}
        if not isinstance(raw, dict):
            raise ValueError(f'{field.label}: expected server ID: domain')
        return {str(server_id).strip(): str(choice).strip().lower() for server_id, choice in raw.items()
                if str(server_id).strip() and str(choice).strip() and str(choice).strip().lower() != 'auto'}
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

    # Older configs list servers with a fixed port instead of a domain per server
    old_fixed = (file_data.get('address') or {}).get('excluded_servers')
    if 'address.fixed' in missing and old_fixed:
        values['address.fixed'] = {str(server_id): KEEP_PORT for server_id in old_fixed}

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
