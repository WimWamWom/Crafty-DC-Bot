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

# Look of wimwamwom.de: dark ground, Space Grotesk with JetBrains Mono for small print,
# tiles with a thin border and three accent colours that rotate over the tabs.
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700'
         '&family=JetBrains+Mono:wght@400;500&display=swap">')

ACCENTS = ['#d4f25a', '#ff8a4c', '#b39cff']

STYLE = """
:root { --bg: #111110; --surface: #1a1a18; --plate: #161615; --field: #111110; --line: #2c2c2a;
        --line-strong: #4a4a46; --text: #f1f0ec; --muted: #a3a29c; --soft: #c4c3bd; --dim: #8f8e88;
        --dark: #111110; --accent: #d4f25a; --good: #d4f25a; --bad: #ff6b5b; color-scheme: dark;
        --sans: "Space Grotesk", system-ui, sans-serif; --mono: "JetBrains Mono", ui-monospace, monospace; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font: 15px/1.5 var(--sans); min-height: 100vh; }
::selection { background: var(--accent); color: var(--dark); }
:focus-visible { outline: 2px solid var(--text); outline-offset: 3px; }
.wrap { max-width: 1160px; margin: 0 auto; padding: 48px 24px 120px; display: flex; flex-direction: column; gap: 32px; }

header { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: 20px; }
.brand { display: flex; align-items: center; gap: 20px; }
.brand img { width: clamp(56px, 8vw, 88px); height: clamp(56px, 8vw, 88px); object-fit: contain; flex: none; }
h1 { font-size: clamp(40px, 8vw, 96px); line-height: .92; letter-spacing: -.04em; font-weight: 700; }
h1 span { color: #d4f25a; }
header p { margin-top: 12px; font-size: 19px; color: var(--muted); }
.count { font: 13px var(--mono); color: var(--muted); display: flex; align-items: center; gap: 8px; }
.count i { width: 8px; height: 8px; border-radius: 2px; background: var(--dim); }
.count.ok i { background: #d4f25a; }
.count.err i { background: var(--bad); }

nav.tabs { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }
.content { display: flex; flex-direction: column; gap: 24px; width: 100%; }
nav.tabs a { position: relative; display: flex; align-items: center; justify-content: space-between; gap: 8px;
             padding: 14px 16px; white-space: nowrap; border: 1px solid var(--line); border-radius: 4px; background: var(--surface);
             color: var(--text); text-decoration: none; font-weight: 600; font-size: 16px; letter-spacing: -.01em;
             transition: transform .25s ease, box-shadow .25s ease, border-color .25s ease, background .2s ease; }
nav.tabs a .label { display: flex; align-items: center; gap: 8px; }
nav.tabs a .dot { width: 8px; height: 8px; border-radius: 2px; background: var(--accent); flex: none; }
nav.tabs a:hover { transform: translateY(-3px); box-shadow: 0 18px 44px rgba(0, 0, 0, .6); border-color: var(--accent); }
nav.tabs a.active { background: var(--accent); border-color: var(--accent); color: var(--dark); }
nav.tabs a.active .dot { background: var(--dark); }
nav.tabs a.has-error::after { content: "!"; position: absolute; top: -8px; right: -8px; width: 20px; height: 20px;
                              border-radius: 2px; background: var(--bad); color: var(--dark); font: 700 12px/20px var(--mono);
                              text-align: center; }

.tab { display: none; flex-direction: column; gap: 16px; }
.tab.active { display: flex; }
.tab-head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: 8px 20px;
            padding-bottom: 4px; }
.tab-head h2 { font-size: clamp(28px, 4vw, 44px); line-height: 1; letter-spacing: -.03em; font-weight: 700; }
.tab-head h2 span { color: var(--accent); }
.tab-head p { color: var(--soft); font-size: 15px; }
.tab-head .path { font: 12px var(--mono); color: var(--dim); }
.groups { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 460px), 1fr)); gap: 16px; align-items: start; }
.group { border: 1px solid var(--line); border-radius: 4px; background: var(--surface); overflow: hidden; }
.group h3 { display: flex; align-items: center; gap: 8px; padding: 14px 18px; background: var(--plate);
            border-bottom: 1px solid var(--line); font-size: 17px; font-weight: 600; letter-spacing: -.01em; }
.group h3::before { content: ""; width: 8px; height: 8px; border-radius: 2px; background: var(--accent); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 0 18px; padding: 18px; }
.grid .wide { grid-column: 1 / -1; }

.field { margin-bottom: 18px; transition: opacity .15s; min-width: 0; }
.grid > .field:last-child { margin-bottom: 0; }
.field.off { opacity: .4; }
label.name { display: block; font-weight: 600; font-size: 14px; margin-bottom: 6px; }
.help { color: var(--muted); font-size: 13px; line-height: 1.45; margin-top: 6px; }
input[type=text], input[type=password], input[type=number], input[type=time], select, textarea {
  width: 100%; padding: 10px 12px; border: 1px solid var(--line-strong); border-radius: 2px;
  background: var(--field); color: var(--text); font: 14px var(--mono); transition: border-color .2s ease; }
input::placeholder { color: var(--dim); }
input:hover, select:hover, textarea:hover { border-color: var(--dim); }
input:focus, select:focus, textarea:focus { outline: none; border-color: var(--accent); }
textarea { min-height: 120px; line-height: 1.5; resize: vertical; }
select { appearance: none; padding-right: 34px; background-repeat: no-repeat; background-position: right 12px center;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%23a3a29c' stroke-width='1.5'/%3E%3C/svg%3E"); }
input[type=time]::-webkit-calendar-picker-indicator { filter: invert(.7); }
.field.invalid input, .field.invalid select { border-color: var(--bad); }

.switch { display: flex; gap: 12px; align-items: flex-start; cursor: pointer; }
.switch input { appearance: none; flex: none; position: relative; width: 40px; height: 22px; margin-top: 1px;
                border: 1px solid var(--line-strong); border-radius: 2px; background: var(--field); cursor: pointer;
                transition: background .2s ease, border-color .2s ease; }
.switch input::after { content: ""; position: absolute; top: 4px; left: 4px; width: 12px; height: 12px; border-radius: 2px;
                       background: var(--dim); transition: transform .2s ease, background .2s ease; }
.switch input:checked { background: var(--accent); border-color: var(--accent); }
.switch input:checked::after { transform: translateX(18px); background: var(--dark); }
.switch b { font-weight: 600; font-size: 15px; }
.switch .help { margin-top: 2px; }

.checks { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 8px; }
.check { display: flex; gap: 10px; align-items: center; padding: 10px 12px; cursor: pointer; border-radius: 2px;
         border: 1px solid var(--line-strong); background: var(--plate); transition: border-color .2s ease; }
.check:hover { border-color: var(--accent); }
.check input { appearance: none; flex: none; width: 16px; height: 16px; position: relative; border-radius: 2px;
               border: 1px solid var(--line-strong); background: var(--field); cursor: pointer; }
.check input:checked { background: var(--accent); border-color: var(--accent); }
.check input:checked::after { content: ""; position: absolute; left: 4px; top: 1px; width: 5px; height: 9px;
                              border: solid var(--dark); border-width: 0 2px 2px 0; transform: rotate(45deg); }
.check:has(input:checked) { border-color: var(--accent); }
.check.small { display: inline-flex; padding: 0; border: 0; background: none; margin-top: 8px; font-size: 13px; color: var(--muted); }

details { font-size: 13px; color: var(--muted); margin-top: 10px; border: 1px solid var(--line); border-radius: 2px;
          background: var(--plate); padding: 10px 12px; }
details summary { cursor: pointer; font-weight: 600; color: var(--text); }
details summary:hover { color: var(--accent); }
details ul { margin-top: 8px; padding-left: 18px; }
details li.head { list-style: none; margin: 10px 0 2px -18px; font-weight: 600; color: var(--text); }

.notice { padding: 14px 18px; border: 1px solid; border-radius: 4px; font-size: 14px; display: flex; gap: 10px; }
.notice::before { content: ""; width: 8px; height: 8px; border-radius: 2px; background: currentColor; flex: none; margin-top: 6px; }
.notice.ok { color: #d4f25a; background: rgba(212, 242, 90, .07); }
.notice.err { color: var(--bad); background: rgba(255, 107, 91, .07); }

.savebar { position: fixed; left: 0; right: 0; bottom: 0; z-index: 5; background: rgba(17, 17, 16, .9);
           backdrop-filter: blur(8px); border-top: 1px solid var(--line); }
.savebar .inner { max-width: 1160px; margin: 0 auto; padding: 14px 24px; display: flex; align-items: center;
                  justify-content: space-between; gap: 16px; }
.savebar small { font: 12px var(--mono); color: var(--dim); }
button { flex: none; display: inline-flex; align-items: center; gap: 14px; border: 1px solid #d4f25a; border-radius: 4px;
         background: #d4f25a; color: var(--dark); padding: 6px 6px 6px 18px; font: 700 15px var(--sans);
         letter-spacing: -.01em; cursor: pointer; transition: transform .25s ease, box-shadow .25s ease; }
button .go { width: 34px; height: 34px; border-radius: 2px; background: var(--dark); color: #d4f25a;
             display: flex; align-items: center; justify-content: center; font-size: 16px; }
button:hover { transform: translateY(-2px); box-shadow: 0 12px 30px rgba(0, 0, 0, .6); }
footer { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; font: 13px var(--mono);
         color: var(--muted); border-top: 1px solid var(--line); padding-top: 20px; }
footer a { color: inherit; text-decoration: none; }
footer a:hover { color: var(--text); }
@media (max-width: 560px) {
  .wrap { padding: 32px 16px 110px; gap: 24px; }
  .savebar .inner { padding: 12px 16px; }
  .savebar small { display: none; }
  .savebar button { width: 100%; justify-content: space-between; }
  nav.tabs { grid-template-columns: repeat(2, 1fr); }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } nav.tabs a:hover, button:hover { transform: none; } }
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
        return self._page('<div class="notice ok">Gespeichert. Der Bot startet neu, '
                          'die Seite lädt in ein paar Sekunden neu.</div>',
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
        for index, (section, title) in enumerate(cfg.SECTIONS.items()):
            tab_label, intro, groups = TABS.get(section, (title, '', []))
            section_fields = [name for name, field in cfg.FIELDS_BY_NAME.items() if field.section == section]
            listed = {name for _, names in groups for name in names}
            leftover = [name for name in section_fields if name not in listed]
            groups = [(group, [name for name in names if name in cfg.FIELDS_BY_NAME]) for group, names in groups]
            if leftover:
                groups.append(('Weitere' if groups else title, leftover))
            accent = f'style="--accent:{ACCENTS[index % len(ACCENTS)]}"'

            error_class = ' has-error' if invalid.intersection(section_fields) else ''
            nav.append(f'<a href="#{section}" data-tab="{section}" class="{error_class.strip()}" {accent}>'
                       f'<span class="label"><i class="dot"></i>{escape(tab_label)}</span></a>')

            html = [f'<section class="tab" id="tab-{section}" {accent}><div class="tab-head"><div>'
                    f'<h2>{escape(title)}<span>.</span></h2>']
            if intro:
                html.append(f'<p>{escape(intro)}</p>')
            html.append(f'</div><span class="path">{len(groups)} {"Gruppe" if len(groups) == 1 else "Gruppen"} · '
                        f'{len(section_fields)} {"Einstellung" if len(section_fields) == 1 else "Einstellungen"}'
                        f'</span></div><div class="groups">')
            for group, names in groups:
                html.append(f'<div class="group"><h3>{escape(group)}</h3><div class="grid">')
                for name in names:
                    html.append(self._render_field(name, cfg.FIELDS_BY_NAME[name], values[name], guild, servers,
                                                   name in invalid))
                html.append('</div></div>')
            html.append('</div></section>')
            panels.append(''.join(html))

        if not self.bot.is_ready():
            state = '<span class="count err"><i></i>Bot offline</span>'
        elif guild is None:
            state = '<span class="count"><i></i>Kein Discord-Server</span>'
        else:
            state = f'<span class="count ok"><i></i>Online auf {escape(guild.name)}</span>'

        body = (f'<nav class="tabs">{"".join(nav)}</nav>'
                f'<form method="post" class="content">{"".join(notices)}{"".join(panels)}'
                f'<div class="savebar"><div class="inner"><small>Speichert alle Bereiche, danach startet der Bot neu.</small>'
                f'<button type="submit">Speichern und neu starten<span class="go" aria-hidden="true">→</span>'
                f'</button></div></div></form>')
        return self._page(body, state=state)

    @staticmethod
    def _page(body: str, head: str = '', state: str = '') -> web.Response:
        html = (f'<!doctype html><html lang="de"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width, initial-scale=1">'
                f'<meta name="color-scheme" content="dark"><meta name="theme-color" content="#111110">'
                f'<title>Crafty Bot</title><link rel="icon" href="{LOGO_URL}">{FONTS}<style>{STYLE}</style>{head}</head>'
                f'<body><div class="wrap"><header><div class="brand"><img src="{LOGO_URL}" alt="">'
                f'<div><h1>Crafty Bot<span>.</span></h1><p>Einstellungen</p></div></div>{state}</header>'
                f'{body}<footer><span>Crafty Bot · Port {cfg.config["web.port"]}</span>'
                f'<span>{escape(cfg.CONFIG_PATH)}</span></footer></div>{SCRIPT}</body></html>')
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
