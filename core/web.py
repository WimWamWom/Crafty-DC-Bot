"""
This module contains a simple web interface to edit the bot configuration.
"""

import asyncio
import base64
import binascii
import hmac
from html import escape
from typing import Callable
from urllib.parse import urlparse

import discord
from aiohttp import web

from core import config as cfg
from core.constants import LOGO_URL
from core.server import get_servers

# Look of wimwamwom.de ("Karbon & Gold"): carbon ground, warm-white type, one gold accent,
# structure through hairlines instead of boxes. Dark only, like the website.
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700'
         '&family=Source+Serif+4:opsz,wght@8..60,500;8..60,600&display=swap">')

STYLE = """
:root { --bg: #0a0a0a; --surface-2: #16130e; --surface-hover: #1a1712; --field: #191611;
        --ink: #f2efe8; --muted: #a09b90; --muted-2: #79746a; --line: #282723; --line-strong: #47433b;
        --accent: #d9a441; --accent-strong: #e6b455; --accent-ink: #141005; --accent-soft: #1f180b;
        --good: #8fc177; --good-soft: #141a10; --bad: #d4655b; --bad-soft: #221211;
        --sans: Inter, ui-sans-serif, system-ui, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        --serif: "Source Serif 4", Georgia, "Times New Roman", serif;
        --mono: ui-monospace, "SF Mono", "Cascadia Code", Consolas, monospace; color-scheme: dark; }
* { box-sizing: border-box; }
html { font-size: 16px; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.55 var(--sans);
       -webkit-font-smoothing: antialiased; }
::selection { background: var(--accent); color: var(--accent-ink); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
a { color: var(--ink); }
.wrap { max-width: 880px; margin: 0 auto; padding: 0 16px; }

header { border-bottom: 1px solid var(--line); }
.top { display: flex; align-items: center; gap: 14px; padding-top: 22px; padding-bottom: 18px; }
.top img { width: 44px; height: 44px; }
.top h1 { font: 600 28px/1.1 var(--serif); letter-spacing: -0.01em; margin: 0; }
.top h1 span { color: var(--accent); }
.top .sub { color: var(--muted); font-size: 13px; margin-top: 2px; }
.pill { margin-left: auto; display: inline-flex; align-items: center; gap: 7px; white-space: nowrap;
        border: 1px solid var(--line-strong); padding: 4px 10px; font-size: 11px; font-weight: 700;
        letter-spacing: .12em; text-transform: uppercase; color: var(--muted); }
.pill::before { content: ""; width: 7px; height: 7px; background: var(--muted-2); }
.pill.ok { color: var(--good); border-color: var(--good); }
.pill.ok::before { background: var(--good); }
.pill.err { color: var(--bad); border-color: var(--bad); }
.pill.err::before { background: var(--bad); }

nav.tabs { position: sticky; top: 0; z-index: 5; background: var(--bg); border-bottom: 1px solid var(--line); }
nav.tabs .wrap { display: flex; gap: 22px; overflow-x: auto; scrollbar-width: none; }
nav.tabs .wrap::-webkit-scrollbar { display: none; }
nav.tabs a { position: relative; flex: none; padding: 14px 2px; border-bottom: 2px solid transparent;
             color: var(--muted); text-decoration: none; font-size: 13px; font-weight: 600;
             letter-spacing: .04em; text-transform: uppercase; transition: color .15s, border-color .15s; }
nav.tabs a:hover { color: var(--ink); }
nav.tabs a.active { color: var(--ink); border-bottom-color: var(--accent); }
nav.tabs a.has-error::after { content: ""; position: absolute; top: 12px; right: -8px;
                              width: 6px; height: 6px; background: var(--bad); }

main { padding: 28px 0 120px; }
.tab { display: none; }
.tab.active { display: block; }
.tab > h2 { font: 600 24px/1.2 var(--serif); margin: 0 0 6px; }
.tab > .intro { color: var(--muted); margin: 0 0 28px; max-width: 640px; }
.group { border-top: 1px solid var(--line); padding-top: 16px; margin-bottom: 34px; }
.group h3 { display: flex; align-items: center; gap: 9px; margin: 0 0 18px; font: 700 11px/1 var(--sans);
            letter-spacing: .16em; text-transform: uppercase; color: var(--muted); }
.group h3::before { content: ""; width: 3px; height: 10px; background: var(--accent); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 0 28px; }
.grid .wide { grid-column: 1 / -1; }

.field { margin-bottom: 20px; transition: opacity .15s; }
.field.off { opacity: .4; }
label.name { display: block; font-weight: 600; font-size: 14px; margin-bottom: 6px; }
.help { color: var(--muted); font-size: 13px; margin-top: 6px; max-width: 640px; }
input[type=text], input[type=password], input[type=number], input[type=time], select, textarea {
  width: 100%; padding: 9px 11px; border: 1px solid var(--line-strong); border-radius: 0;
  background: var(--field); color: var(--ink); font: inherit; transition: border-color .15s; }
input:hover, select:hover, textarea:hover { border-color: var(--muted-2); }
input:focus, select:focus, textarea:focus { outline: none; border-color: var(--accent); }
textarea { min-height: 120px; font: 13px/1.5 var(--mono); resize: vertical; }
select { appearance: none; padding-right: 32px; background-repeat: no-repeat; background-position: right 11px center;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%23a09b90' stroke-width='1.5'/%3E%3C/svg%3E"); }
input[type=time]::-webkit-calendar-picker-indicator { filter: invert(.7); }
.field.invalid input, .field.invalid select { border-color: var(--bad); }

.switch { display: flex; gap: 12px; align-items: flex-start; cursor: pointer; }
.switch input { appearance: none; flex: none; position: relative; width: 38px; height: 20px; margin: 1px 0 0;
                border: 1px solid var(--line-strong); background: var(--field); cursor: pointer;
                transition: background .15s, border-color .15s; }
.switch input::after { content: ""; position: absolute; top: 3px; left: 3px; width: 12px; height: 12px;
                       background: var(--muted); transition: transform .15s, background .15s; }
.switch input:checked { background: var(--accent-soft); border-color: var(--accent); }
.switch input:checked::after { transform: translateX(18px); background: var(--accent); }
.switch b { font-weight: 600; font-size: 14px; }
.switch .help { margin-top: 2px; }

.checks { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 6px; }
.check { display: flex; gap: 10px; align-items: center; padding: 9px 11px; cursor: pointer;
         border: 1px solid var(--line); background: var(--surface-2); transition: border-color .15s; }
.check:hover { border-color: var(--line-strong); }
.check input { appearance: none; flex: none; width: 16px; height: 16px; margin: 0; position: relative;
               border: 1px solid var(--line-strong); background: var(--field); cursor: pointer; }
.check input:checked { background: var(--accent); border-color: var(--accent); }
.check input:checked::after { content: ""; position: absolute; left: 4px; top: 1px; width: 5px; height: 9px;
                              border: solid var(--accent-ink); border-width: 0 2px 2px 0; transform: rotate(45deg); }
.check:has(input:checked) { border-color: var(--accent); }
.check.small { display: inline-flex; padding: 0; border: 0; background: none; margin-top: 8px;
               font-size: 13px; color: var(--muted); }

details { color: var(--muted); font-size: 13px; margin-top: 10px; border-left: 2px solid var(--line-strong);
          padding: 2px 0 2px 12px; }
details summary { cursor: pointer; font-weight: 600; color: var(--ink); }
details summary:hover { color: var(--accent); }
details ul { margin: 8px 0 0; padding-left: 18px; }
details li.head { list-style: none; margin: 10px 0 2px -18px; font-weight: 600; color: var(--ink); }

.notice { padding: 12px 16px; margin-bottom: 22px; border: 1px solid; font-size: 14px; }
.notice.ok { background: var(--good-soft); color: var(--good); }
.notice.err { background: var(--bad-soft); color: var(--bad); }

.savebar { position: fixed; left: 0; right: 0; bottom: 0; z-index: 5; background: rgba(10, 10, 10, .92);
           backdrop-filter: blur(6px); border-top: 1px solid var(--line); }
.savebar .wrap { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 12px 16px; }
.savebar small { color: var(--muted-2); font-size: 12px; }
button { flex: none; border: 1px solid var(--accent); background: var(--accent); color: var(--accent-ink);
         padding: 10px 18px; font: 700 12px/1 var(--sans); letter-spacing: .08em; text-transform: uppercase;
         cursor: pointer; transition: background .15s, border-color .15s; }
button:hover { background: var(--accent-strong); border-color: var(--accent-strong); }
@media (max-width: 560px) {
  .top h1 { font-size: 23px; }
  .top .sub { display: none; }
  .savebar small { display: none; }
  .savebar button { width: 100%; }
}
"""

SCRIPT = """<script>
// Tabs: all settings stay in one form, the tabs only show one part of it. The open tab is kept in the URL.
var tabs = Array.prototype.slice.call(document.querySelectorAll('nav.tabs a'));
function showTab(id) {
  if (!document.getElementById('tab-' + id)) id = tabs.length ? tabs[0].dataset.tab : '';
  tabs.forEach(function (tab) {
    var active = tab.dataset.tab === id;
    tab.classList.toggle('active', active);
    document.getElementById('tab-' + tab.dataset.tab).classList.toggle('active', active);
    if (active) tab.scrollIntoView({block: 'nearest', inline: 'nearest'});
  });
}
tabs.forEach(function (tab) {
  tab.addEventListener('click', function (event) {
    event.preventDefault();
    history.replaceState(null, '', '#' + tab.dataset.tab);
    showTab(tab.dataset.tab);
  });
});
var firstError = document.querySelector('nav.tabs a.has-error');
showTab(firstError ? firstError.dataset.tab : location.hash.slice(1));

// Dim settings whose on/off switch is off. The value is still submitted, so it is kept for later.
document.querySelectorAll('[data-toggled-by]').forEach(function (field) {
  var toggle = document.getElementById(field.dataset.toggledBy);
  if (!toggle) return;
  var update = function () { field.classList.toggle('off', !toggle.checked); };
  toggle.addEventListener('change', update);
  update();
});
</script>"""

WEEKDAYS = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']

# One tab per config section: short tab label, intro line and groups of fields.
# Fields of a section that are not listed in a group end up in an extra group at the end.
TABS = {
    'crafty': ('Crafty', 'Verbindung zu deinem Crafty Controller.', [
        ('Verbindung', ['crafty.url', 'crafty.token']),
    ]),
    'discord': ('Discord', 'Bot-Token, Discord-Server und wer den Bot wo benutzen darf.', [
        ('Bot', ['discord.token', 'discord.guild_id']),
        ('Befehlskanal', ['discord.command_channel_enabled', 'discord.command_channel_id']),
        ('Steuer-Rolle', ['discord.control_role_enabled', 'discord.control_role_id']),
    ]),
    'servers': ('Server', 'Welche Crafty-Server im Bot auftauchen.', [
        ('Verfügbare Server', ['servers.allowed']),
    ]),
    'auto_stop': ('Auto-Stop', 'Leere Server automatisch herunterfahren.', [
        ('Auto-Stop', ['auto_stop.enabled', 'auto_stop.interval']),
    ]),
    'status': ('Status', 'Eine Nachricht mit allen Servern, die sich selbst aktualisiert.', [
        ('Statusübersicht', ['status.enabled', 'status.channel_id', 'status.update_interval']),
    ]),
    'backup': ('Backups', 'Automatische Backups, die der Bot in Crafty anlegt und aufräumt.', [
        ('Allgemein', ['backup.enabled', 'backup.compress']),
        ('Zeitplan und Anzahl', ['backup.on_start', 'backup.daily', 'backup.weekly',
                                 'backup.time', 'backup.weekday', 'backup.timezone']),
        ('Inhalt', ['backup.excluded_dirs', 'backup.before_command', 'backup.after_command', 'backup.timeout']),
        ('Server ohne Backups', ['backup.excluded_servers', 'backup.delete_excluded']),
        ('Aufräumen', ['backup.delete_after_days']),
    ]),
    'web': ('Webinterface', 'Zugang zu dieser Seite.', [
        ('Zugang', ['web.port', 'web.password']),
    ]),
}

# Fields that take the full width of a group instead of one grid column
WIDE_KINDS = ('bool', 'servers', 'list')


class WebInterface:
    """
    Serves the config form and saves changes to the config file.

    Args:
        bot: The Discord bot, used to list channels and roles of the guild.
        on_saved: Called after the config was saved (restarts the bot).
    """

    def __init__(self, bot: discord.Client, on_saved: Callable[[], None]):
        self.bot = bot
        self.on_saved = on_saved
        self.app = web.Application(middlewares=[self.auth_middleware])
        self.app.add_routes([web.get('/', self.index), web.post('/', self.save)])
        self.runner: web.AppRunner | None = None

    async def start(self, port: int) -> None:
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        await web.TCPSite(self.runner, '0.0.0.0', port).start()
        print(f'Web interface running on port {port}')

    @web.middleware
    async def auth_middleware(self, request: web.Request, handler):
        password = cfg.config['web.password']
        if password and not self._check_password(request, password):
            return web.Response(status=401, text='Login required',
                                headers={'WWW-Authenticate': 'Basic realm="Crafty Bot"'})
        return await handler(request)

    @staticmethod
    def _check_password(request: web.Request, password: str) -> bool:
        header = request.headers.get('Authorization', '')
        if not header.startswith('Basic '):
            return False
        try:
            _, _, given = base64.b64decode(header[6:]).decode().partition(':')
        except (binascii.Error, UnicodeDecodeError):
            return False
        return hmac.compare_digest(given.encode(), password.encode())

    def _guild(self) -> discord.Guild | None:
        if not self.bot.is_ready() or not cfg.config['discord.guild_id']:
            return None
        return self.bot.get_guild(cfg.config['discord.guild_id'])

    async def index(self, request: web.Request) -> web.Response:
        return await self.render()

    async def save(self, request: web.Request) -> web.Response:
        # reject form posts from other sites
        origin = request.headers.get('Origin')
        if origin and urlparse(origin).netloc != request.host:
            return web.Response(status=403, text='Forbidden')

        form = await request.post()
        values = dict(cfg.config)
        errors = []
        invalid = set()
        for name, field in cfg.FIELDS_BY_NAME.items():
            if field.kind == 'bool':
                values[name] = name in form
            elif field.kind == 'servers':
                if f'{name}.present' in form:
                    values[name] = cfg.parse_value(field, form.getall(name, []))
            elif field.kind == 'secret':
                if f'{name}.clear' in form:
                    values[name] = ''
                elif form.get(name):
                    values[name] = cfg.parse_value(field, form[name])
            else:
                try:
                    values[name] = cfg.parse_value(field, form.get(name, ''))
                except ValueError:
                    errors.append(f'{field.label}: ungültiger Wert')
                    invalid.add(name)

        for name, field in cfg.FIELDS_BY_NAME.items():
            if field.required and not values[name]:
                errors.append(f'{field.label} fehlt')
                invalid.add(name)
        for toggle, target in cfg.TOGGLES.items():
            if values[toggle] and not values[target]:
                errors.append(f'{cfg.FIELDS_BY_NAME[target].label}: bitte auswählen oder den Schalter ausschalten')
                invalid.add(target)
        if errors:
            return await self.render(errors=errors, values=values, invalid=invalid)

        try:
            cfg.save(values)
        except OSError as e:
            return await self.render(errors=[f'Speichern fehlgeschlagen: {e}'], values=values)

        print('Config saved via web interface, restarting')
        # give the browser time to receive the response before restarting
        asyncio.get_running_loop().call_later(1, self.on_saved)
        return self._page('<main><div class="wrap"><div class="notice ok">Gespeichert. Der Bot startet neu, '
                          'die Seite lädt in ein paar Sekunden neu.</div></div></main>',
                          head='<meta http-equiv="refresh" content="5;url=/">')

    async def render(self, errors: list[str] | None = None, values: dict | None = None,
                     invalid: set[str] | None = None) -> web.Response:
        values = values or cfg.config
        invalid = invalid or set()
        guild = self._guild()
        try:
            servers = await get_servers(include_all=True) if values['crafty.url'] and values['crafty.token'] else None
        except Exception as e:
            print(f'web: failed to get server list: {e}')
            servers = None

        notices = []
        if errors:
            notices.append('<div class="notice err">' + '<br>'.join(escape(e) for e in errors) + '</div>')
        missing = cfg.missing_required(cfg.config)
        if missing and not errors:
            notices.append('<div class="notice err">Der Bot läuft nicht, es fehlt: '
                           + escape(', '.join(missing)) + '</div>')
        if not cfg.config['web.password']:
            notices.append('<div class="notice err">Das Webinterface hat kein Passwort. '
                           'Setze im Tab „Webinterface“ eins, wenn der Port von außen erreichbar ist.</div>')

        nav = []
        panels = []
        for section, title in cfg.SECTIONS.items():
            tab_label, intro, groups = TABS.get(section, (title, '', []))
            section_fields = [name for name, field in cfg.FIELDS_BY_NAME.items() if field.section == section]
            listed = {name for _, names in groups for name in names}
            leftover = [name for name in section_fields if name not in listed]
            groups = [(group, [name for name in names if name in cfg.FIELDS_BY_NAME]) for group, names in groups]
            if leftover:
                groups.append(('Weitere' if groups else title, leftover))

            error_class = ' has-error' if invalid.intersection(section_fields) else ''
            nav.append(f'<a href="#{section}" data-tab="{section}" class="{error_class.strip()}">'
                       f'{escape(tab_label)}</a>')

            html = [f'<div class="tab" id="tab-{section}"><h2>{escape(title)}</h2>']
            if intro:
                html.append(f'<p class="intro">{escape(intro)}</p>')
            for group, names in groups:
                html.append(f'<div class="group"><h3>{escape(group)}</h3><div class="grid">')
                for name in names:
                    html.append(self._render_field(name, cfg.FIELDS_BY_NAME[name], values[name], guild, servers,
                                                   name in invalid))
                html.append('</div></div>')
            html.append('</div>')
            panels.append(''.join(html))

        if not self.bot.is_ready():
            state = '<span class="pill err">Offline</span>'
        elif guild is None:
            state = '<span class="pill">Kein Discord-Server</span>'
        else:
            state = f'<span class="pill ok" title="{escape(guild.name)}">Online</span>'

        body = (f'<nav class="tabs"><div class="wrap">{"".join(nav)}</div></nav>'
                f'<form method="post"><main><div class="wrap">{"".join(notices)}{"".join(panels)}</div></main>'
                f'<div class="savebar"><div class="wrap"><small>Speichert alle Tabs. Der Bot startet danach neu.</small>'
                f'<button type="submit">Speichern und neu starten</button></div></div></form>')
        return self._page(body, state=state)

    @staticmethod
    def _page(body: str, head: str = '', state: str = '') -> web.Response:
        html = (f'<!doctype html><html lang="de"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width, initial-scale=1">'
                f'<meta name="color-scheme" content="dark"><meta name="theme-color" content="#0a0a0a">'
                f'<title>Crafty Bot</title><link rel="icon" href="{LOGO_URL}">{FONTS}<style>{STYLE}</style>{head}</head>'
                f'<body><header><div class="wrap top"><img src="{LOGO_URL}" alt="">'
                f'<div><h1>Crafty Bot<span>.</span></h1><div class="sub">Einstellungen</div></div>{state}</div></header>'
                f'{body}{SCRIPT}</body></html>')
        return web.Response(text=html, content_type='text/html')

    @staticmethod
    def _render_field(name: str, field: cfg.Field, value, guild: discord.Guild | None,
                      servers: list[dict] | None, invalid: bool = False) -> str:
        classes = ['field']
        if field.kind in WIDE_KINDS or field.details:
            classes.append('wide')
        if invalid:
            classes.append('invalid')
        # lets the page dim the setting while its switch is off
        toggled_by = f' data-toggled-by="{cfg.TOGGLED_BY[name]}"' if name in cfg.TOGGLED_BY else ''
        open_tag = f'<div class="{" ".join(classes)}"{toggled_by}>'
        label = f'<label class="name" for="{name}">{escape(field.label)}</label>'
        help_text = f'<div class="help">{escape(field.help)}</div>' if field.help else ''
        if field.details:
            # lines ending with a colon are headings
            items = ''.join(f'<li class="head">{escape(line)}</li>' if line.endswith(':')
                            else f'<li>{escape(line)}</li>' for line in field.details.splitlines())
            help_text += f'<details><summary>Hinweise</summary><ul>{items}</ul></details>'

        if field.kind == 'bool':
            checked = ' checked' if value else ''
            return (f'{open_tag}<label class="switch"><input type="checkbox" id="{name}" name="{name}"{checked}>'
                    f'<span><b>{escape(field.label)}</b>{help_text}</span></label></div>')

        if field.kind == 'secret':
            placeholder = '•••••••• (unverändert lassen)' if value else 'nicht gesetzt'
            clear = ''
            if value and not field.required:
                clear = (f'<label class="check small"><input type="checkbox" name="{name}.clear">'
                         f'entfernen</label>')
            return (f'{open_tag}{label}<input type="password" id="{name}" name="{name}" '
                    f'autocomplete="new-password" placeholder="{placeholder}">{clear}{help_text}</div>')

        if field.kind in ('channel', 'role') and guild is not None:
            if field.kind == 'channel':
                options = [(channel.id, f'#{channel.name}') for channel in guild.text_channels]
            else:
                options = [(role.id, f'@{role.name}') for role in reversed(guild.roles) if not role.is_default()]
            html_options = ['<option value="0">— bitte wählen —</option>']
            if value and value not in [option_id for option_id, _ in options]:
                html_options.append(f'<option value="{value}" selected>Unbekannt ({value})</option>')
            for option_id, option_name in options:
                selected = ' selected' if option_id == value else ''
                html_options.append(f'<option value="{option_id}"{selected}>{escape(option_name)}</option>')
            return (f'{open_tag}{label}<select id="{name}" name="{name}">'
                    f'{"".join(html_options)}</select>{help_text}</div>')

        if field.kind == 'list':
            return (f'{open_tag}{label}<textarea id="{name}" name="{name}">'
                    f'{escape(chr(10).join(value))}</textarea>{help_text}</div>')

        if field.kind == 'weekday':
            options = ''.join(f'<option value="{day}"{" selected" if day == value else ""}>{day_name}</option>'
                              for day, day_name in enumerate(WEEKDAYS))
            return f'{open_tag}{label}<select id="{name}" name="{name}">{options}</select>{help_text}</div>'

        if field.kind == 'time':
            return (f'{open_tag}{label}<input type="time" id="{name}" name="{name}" '
                    f'value="{escape(value)}">{help_text}</div>')

        if field.kind == 'servers':
            marker = f'<input type="hidden" name="{name}.present" value="1">'
            if servers is None:
                # keep the current selection if the server list is not available
                hidden = ''.join(f'<input type="hidden" name="{name}" value="{escape(server_id)}">'
                                 for server_id in value)
                return (f'{open_tag}<label class="name">{escape(field.label)}</label>{marker}{hidden}'
                        f'<div class="help">Serverliste konnte nicht von Crafty geladen werden. '
                        f'Prüfe URL und Token im Tab „Crafty“.</div></div>')
            checks = []
            for server in servers:
                server_id = server['server_id']
                checked = ' checked' if server_id in value else ''
                checks.append(f'<label class="check"><input type="checkbox" name="{name}" '
                              f'value="{escape(server_id)}"{checked}>{escape(server["server_name"])}</label>')
            if not servers:
                checks.append('<div class="help">Keine Server in Crafty gefunden.</div>')
            return (f'{open_tag}<label class="name">{escape(field.label)}</label>{marker}'
                    f'<div class="checks">{"".join(checks)}</div>{help_text}</div>')

        # Discord IDs are too large for number inputs
        input_type = 'number' if field.kind == 'int' else 'text'
        mode = ' inputmode="numeric"' if field.kind in ('channel', 'role') else ''
        return (f'{open_tag}{label}<input type="{input_type}"{mode} id="{name}" name="{name}" '
                f'value="{escape(str(value))}">{help_text}</div>')
