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
from core.server import get_servers

STYLE = """
:root { --bg: #f4f5f7; --card: #fff; --text: #1d2127; --muted: #636b75; --border: #d9dde3;
        --accent: #3b82f6; --ok-bg: #e7f6ec; --ok: #1a7f37; --err-bg: #fdecec; --err: #b42318; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #15181d; --card: #1e2229; --text: #e6e8eb; --muted: #9aa3ad; --border: #343a44;
          --accent: #60a5fa; --ok-bg: #12301d; --ok: #6fdd8b; --err-bg: #3a1717; --err: #ff8a80; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
       font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 760px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 24px; margin: 0 0 4px; }
.sub { color: var(--muted); margin: 0 0 24px; }
section { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
          padding: 16px 20px; margin-bottom: 16px; }
h2 { font-size: 16px; margin: 0 0 12px; }
.field { margin-bottom: 14px; }
.field:last-child { margin-bottom: 0; }
label.name { display: block; font-weight: 600; margin-bottom: 4px; }
.help { color: var(--muted); font-size: 13px; margin-top: 3px; }
input[type=text], input[type=password], input[type=number], select {
  width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg); color: var(--text); font: inherit; }
.check { display: flex; gap: 8px; align-items: center; margin: 4px 0; }
.check small { color: var(--muted); }
textarea { width: 100%; min-height: 110px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px;
           background: var(--bg); color: var(--text); font: 14px/1.4 ui-monospace, monospace; }
details { color: var(--muted); font-size: 13px; margin-top: 6px; }
details summary { cursor: pointer; }
details ul { margin: 6px 0 0; padding-left: 18px; }
details li.head { list-style: none; margin: 8px 0 2px -18px; font-weight: 600; color: var(--text); }
.notice { padding: 10px 14px; border-radius: 8px; margin-bottom: 16px; }
.notice.ok { background: var(--ok-bg); color: var(--ok); }
.notice.err { background: var(--err-bg); color: var(--err); }
.field.off { opacity: .45; }
button { background: var(--accent); color: #fff; border: 0; border-radius: 6px;
         padding: 10px 20px; font: inherit; font-weight: 600; cursor: pointer; }
"""

# Dim settings whose on/off switch is off. The value is still submitted, so it is kept for later.
SCRIPT = """<script>
document.querySelectorAll('[data-toggled-by]').forEach(function (field) {
  var toggle = document.getElementById(field.dataset.toggledBy);
  if (!toggle) return;
  var update = function () { field.classList.toggle('off', !toggle.checked); };
  toggle.addEventListener('change', update);
  update();
});
</script>"""

WEEKDAYS = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']


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

        errors += [f'{label} fehlt' for label in cfg.missing_required(values)]
        errors += [f'{label}: bitte auswählen oder den Schalter ausschalten' for label in cfg.missing_toggled(values)]
        if errors:
            return await self.render(errors=errors, values=values)

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

    async def render(self, errors: list[str] | None = None, values: dict | None = None) -> web.Response:
        values = values or cfg.config
        guild = self._guild()
        try:
            servers = await get_servers(include_all=True) if values['crafty.url'] and values['crafty.token'] else None
        except Exception as e:
            print(f'web: failed to get server list: {e}')
            servers = None

        body = []
        if errors:
            body.append('<div class="notice err">' + '<br>'.join(escape(e) for e in errors) + '</div>')
        missing = cfg.missing_required(cfg.config)
        if missing and not errors:
            body.append('<div class="notice err">Der Bot läuft nicht, es fehlt: '
                        + escape(', '.join(missing)) + '</div>')
        if not cfg.config['web.password']:
            body.append('<div class="notice err">Das Webinterface hat kein Passwort. '
                        'Setze unten eins, wenn der Port von außen erreichbar ist.</div>')

        body.append('<form method="post">')
        for section, title in cfg.SECTIONS.items():
            body.append(f'<section><h2>{escape(title)}</h2>')
            for name, field in cfg.FIELDS_BY_NAME.items():
                if field.section == section:
                    body.append(self._render_field(name, field, values[name], guild, servers))
            body.append('</section>')
        body.append('<button type="submit">Speichern und Bot neu starten</button></form>')
        return self._page(''.join(body))

    @staticmethod
    def _page(body: str, head: str = '') -> web.Response:
        html = (f'<!doctype html><html lang="de"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width, initial-scale=1">'
                f'<title>Crafty Bot</title><style>{STYLE}</style>{head}</head><body><main>'
                f'<h1>Crafty Bot</h1><p class="sub">Einstellungen</p>{body}</main>{SCRIPT}</body></html>')
        return web.Response(text=html, content_type='text/html')

    @staticmethod
    def _render_field(name: str, field: cfg.Field, value, guild: discord.Guild | None,
                      servers: list[dict] | None) -> str:
        label = f'<label class="name" for="{name}">{escape(field.label)}</label>'
        # lets the page dim the setting while its switch is off
        toggled_by = f' data-toggled-by="{cfg.TOGGLED_BY[name]}"' if name in cfg.TOGGLED_BY else ''
        help_text = f'<div class="help">{escape(field.help)}</div>' if field.help else ''
        if field.details:
            # lines ending with a colon are headings
            items = ''.join(f'<li class="head">{escape(line)}</li>' if line.endswith(':')
                            else f'<li>{escape(line)}</li>' for line in field.details.splitlines())
            help_text += f'<details><summary>Hinweise</summary><ul>{items}</ul></details>'

        if field.kind == 'bool':
            checked = ' checked' if value else ''
            return (f'<div class="field"><label class="check"><input type="checkbox" id="{name}" name="{name}"{checked}>'
                    f'<b>{escape(field.label)}</b></label>{help_text}</div>')

        if field.kind == 'secret':
            placeholder = '•••••••• (unverändert lassen)' if value else 'nicht gesetzt'
            clear = ''
            if value and not field.required:
                clear = (f'<label class="check"><input type="checkbox" name="{name}.clear">'
                         f'<small>entfernen</small></label>')
            return (f'<div class="field">{label}<input type="password" id="{name}" name="{name}" '
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
            return (f'<div class="field"{toggled_by}>{label}<select id="{name}" name="{name}">'
                    f'{"".join(html_options)}</select>{help_text}</div>')

        if field.kind == 'list':
            return (f'<div class="field">{label}<textarea id="{name}" name="{name}">'
                    f'{escape(chr(10).join(value))}</textarea>{help_text}</div>')

        if field.kind == 'weekday':
            options = ''.join(f'<option value="{day}"{" selected" if day == value else ""}>{day_name}</option>'
                              for day, day_name in enumerate(WEEKDAYS))
            return f'<div class="field">{label}<select id="{name}" name="{name}">{options}</select>{help_text}</div>'

        if field.kind == 'time':
            return (f'<div class="field">{label}<input type="time" id="{name}" name="{name}" '
                    f'value="{escape(value)}">{help_text}</div>')

        if field.kind == 'servers':
            marker = f'<input type="hidden" name="{name}.present" value="1">'
            if servers is None:
                # keep the current selection if the server list is not available
                hidden = ''.join(f'<input type="hidden" name="{name}" value="{escape(server_id)}">'
                                 for server_id in value)
                return (f'<div class="field"><label class="name">{escape(field.label)}</label>{marker}{hidden}'
                        f'<div class="help">Serverliste konnte nicht von Crafty geladen werden. '
                        f'Prüfe URL und Token.</div></div>')
            checks = []
            for server in servers:
                server_id = server['server_id']
                checked = ' checked' if server_id in value else ''
                checks.append(f'<label class="check"><input type="checkbox" name="{name}" '
                              f'value="{escape(server_id)}"{checked}>{escape(server["server_name"])}</label>')
            if not servers:
                checks.append('<div class="help">Keine Server in Crafty gefunden.</div>')
            return f'<div class="field"><label class="name">{escape(field.label)}</label>{marker}{"".join(checks)}{help_text}</div>'

        # Discord IDs are too large for number inputs
        input_type = 'number' if field.kind == 'int' else 'text'
        mode = ' inputmode="numeric"' if field.kind in ('channel', 'role') else ''
        return (f'<div class="field"{toggled_by}>{label}<input type="{input_type}"{mode} id="{name}" name="{name}" '
                f'value="{escape(str(value))}">{help_text}</div>')
