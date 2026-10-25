"""
This module creates backups of the Crafty servers based on the backup rule in the config.

The bot manages three backup configurations per server in Crafty ("Bot Start", "Bot Täglich" and
"Bot Wöchentlich"). Crafty keeps max_backups files per configuration and deletes older ones.
The bot runs the backups itself, so it can skip servers that were not online since the last backup.
"""

import asyncio
import json
import os
import time
import traceback
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

import aiohttp

from core import config as cfg
from core.config import get
from core.constants import API_ENDPOINT
from core.network import HttpMethod, send_request
from core.server import get_server_stats, get_servers, server_action

# kind -> (name of the backup configuration in Crafty, config key with the number of backups to keep)
KINDS = {
    'start': ('Bot Start', 'backup.on_start'),
    'daily': ('Bot Täglich', 'backup.daily'),
    'weekly': ('Bot Wöchentlich', 'backup.weekly'),
}
STATE_PATH = os.path.join(os.path.dirname(cfg.CONFIG_PATH), 'backup_state.json')
# how often the backup configurations in Crafty are checked and updated
SYNC_INTERVAL = 3600
# maximum time a scheduled backup may take before the next one starts
SCHEDULED_TIMEOUT = 3 * 3600


class BackupState:
    """
    Remembers when each server was last seen online and when the last backup of each kind was made.
    Stored next to the config file, so it survives restarts.
    """

    def __init__(self):
        self.data = {'servers': {}, 'last_run': {}}
        try:
            with open(STATE_PATH, encoding='utf-8') as file:
                self.data.update(json.load(file))
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            print(f'backup: could not read {STATE_PATH}: {e}')
        # servers never seen online count as inactive since the bot started tracking them
        self.data.setdefault('tracking_since', time.time())

    def save(self) -> None:
        try:
            tmp_path = STATE_PATH + '.tmp'
            with open(tmp_path, 'w', encoding='utf-8') as file:
                json.dump(self.data, file, indent=2)
            os.replace(tmp_path, STATE_PATH)
        except OSError as e:
            print(f'backup: could not write {STATE_PATH}: {e}')

    def _server(self, server_id: str) -> dict:
        return self.data['servers'].setdefault(server_id, {'last_online': 0, 'last_backup': {}})

    def mark_online(self, server_id: str) -> None:
        self._server(server_id)['last_online'] = time.time()

    def mark_backup(self, server_id: str, kind: str, timestamp: float) -> None:
        self._server(server_id)['last_backup'][kind] = timestamp

    def inactive_days(self, server_id: str) -> float:
        last_online = self._server(server_id)['last_online'] or self.data['tracking_since']
        return (time.time() - last_online) / 86400

    def was_online_since_backup(self, server_id: str, kind: str) -> bool:
        """
        True if the server was online after the last backup of this kind, or never had one and was online.
        """
        server = self._server(server_id)
        last_backup = server['last_backup'].get(kind)
        if last_backup is None:
            # no backup of this kind yet: back up if the server was ever seen online
            return kind == 'start' or server['last_online'] > 0
        return server['last_online'] > last_backup


state = BackupState()
# server_id -> kind -> backup_id of the configurations the bot manages
backup_ids: dict[str, dict[str, str]] = {}
# only one backup at a time, so scheduled backups and /start do not compete for the disk
backup_lock = asyncio.Lock()


async def _request(path: str, method: HttpMethod = HttpMethod.GET, data: dict = None) -> tuple[int, dict]:
    """
    Send a request to the Crafty API and return the status code and the JSON body.
    """
    response = await asyncio.to_thread(send_request, path, method=method, data=data)
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code or 0, body if isinstance(body, dict) else {}


def _desired_config(kind: str) -> dict:
    name, count_key = KINDS[kind]
    return {
        'backup_name': name,
        'max_backups': get(count_key),
        'compress': get('backup.compress'),
        'shutdown': False,
        'before': get('backup.before_command'),
        'after': get('backup.after_command'),
        'excluded_dirs': get('backup.excluded_dirs'),
        'backup_type': 'zip_vault',
    }


def _differs(existing: dict, desired: dict) -> bool:
    for key, value in desired.items():
        current = existing.get(key)
        if key == 'excluded_dirs':
            # Crafty stores the list as a comma separated string
            current = [item for item in (current or '').split(',') if item]
        if current != value:
            return True
    return False


async def sync_server(server_id: str) -> dict[str, str]:
    """
    Create or update the backup configurations of the bot for one server.
    Configurations of kinds that are turned off (0 backups) are left untouched.

    Returns:
        dict: kind -> backup_id of the enabled kinds.
    """
    path = f'{API_ENDPOINT}{server_id}/backups'
    status, configs = await _request(path)
    if status != 200:
        print(f'backup: failed to get backup configs of {server_id} ({status})')
        return backup_ids.get(server_id, {})

    by_name = {conf.get('backup_name'): conf for conf in configs.values() if isinstance(conf, dict)}
    location = next((conf.get('backup_location') for conf in configs.values()
                     if isinstance(conf, dict) and conf.get('default')), None)

    ids = {}
    for kind, (name, count_key) in KINDS.items():
        if get(count_key) <= 0:
            continue
        desired = _desired_config(kind)
        existing = by_name.get(name)
        if existing is None:
            # the backup location can only be set by admins, Crafty chooses it for other users
            data = dict(desired, backup_location=location) if location else desired
            status, _ = await _request(path, HttpMethod.POST, data)
            if status != 200 and location:
                status, _ = await _request(path, HttpMethod.POST, desired)
            if status != 200:
                print(f'backup: failed to create "{name}" for {server_id} ({status})')
                continue
            print(f'backup: created "{name}" for {server_id}')
            _, configs = await _request(path)
            existing = next((conf for conf in configs.values()
                             if isinstance(conf, dict) and conf.get('backup_name') == name), None)
            if existing is None:
                continue
        elif _differs(existing, desired):
            status, _ = await _request(f'{path}/backup/{existing["backup_id"]}', HttpMethod.PATCH, desired)
            if status != 200:
                print(f'backup: failed to update "{name}" for {server_id} ({status})')
            else:
                print(f'backup: updated "{name}" for {server_id}')
        ids[kind] = existing['backup_id']

    backup_ids[server_id] = ids
    return ids


def _websocket_url(server_id: str) -> str:
    url = urlparse(get('crafty.url').rstrip('/'))
    scheme = 'wss' if url.scheme == 'https' else 'ws'
    query = urlencode({'page': '/panel/server_detail', 'page_query_params': f'id={server_id}'})
    return f'{scheme}://{url.netloc}{url.path}/ws?{query}'


async def _wait_for_backup(ws: aiohttp.ClientWebSocketResponse, backup_id: str) -> None:
    """
    Wait until Crafty reports the end of the backup. Crafty sends progress updates while zipping and a
    final update with "current_file" when the backup is done or has failed.
    """
    async for message in ws:
        if message.type != aiohttp.WSMsgType.TEXT:
            if message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                break
            continue
        try:
            event = json.loads(message.data)
        except ValueError:
            continue
        data = event.get('data')
        if (event.get('event') == 'backup_status' and isinstance(data, dict)
                and data.get('backup_id') == backup_id and 'current_file' in data):
            return
    raise ConnectionError('websocket closed')


async def run_backup(server_id: str, kind: str, timeout: float) -> bool:
    """
    Run a backup of the given kind and wait until it is finished.

    Crafty only reports the end of a backup over its websocket, so the bot listens there.

    Returns:
        bool: True if the backup was created.
    """
    backup_id = backup_ids.get(server_id, {}).get(kind) or (await sync_server(server_id)).get(kind)
    if backup_id is None:
        print(f'backup: no "{KINDS[kind][0]}" config for {server_id}')
        return False

    try:
        await asyncio.wait_for(backup_lock.acquire(), timeout)
    except asyncio.TimeoutError:
        print(f'backup: another backup is still running, skipping "{KINDS[kind][0]}" for {server_id}')
        return False
    try:
        started = time.time()
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(_websocket_url(server_id), ssl=False, heartbeat=30,
                                          headers={'Cookie': f'token={get("crafty.token")}'}) as ws:
                if not await server_action(server_id, f'backup_server/{backup_id}'):
                    return False
                print(f'backup: started "{KINDS[kind][0]}" for {server_id}')
                await asyncio.wait_for(_wait_for_backup(ws, backup_id), timeout)
    except asyncio.TimeoutError:
        print(f'backup: "{KINDS[kind][0]}" for {server_id} did not finish within {timeout:.0f}s')
        return False
    except (aiohttp.ClientError, ConnectionError, OSError) as e:
        print(f'backup: lost connection to Crafty while backing up {server_id}: {e}')
        return False
    finally:
        backup_lock.release()

    # Crafty marks failed backups in the status of the configuration
    status, conf = await _request(f'{API_ENDPOINT}{server_id}/backups/backup/{backup_id}')
    try:
        failed = json.loads(conf.get('status') or '{}').get('status') == 'Failed'
    except ValueError:
        failed = False
    if status != 200 or failed:
        print(f'backup: "{KINDS[kind][0]}" for {server_id} failed')
        return False

    state.mark_backup(server_id, kind, started)
    state.save()
    print(f'backup: "{KINDS[kind][0]}" for {server_id} done')
    return True


def is_excluded(server_id: str) -> bool:
    return server_id in get('backup.excluded_servers')


def needs_start_backup(server_id: str) -> bool:
    return (get('backup.enabled') and get('backup.on_start') > 0 and not is_excluded(server_id)
            and state.was_online_since_backup(server_id, 'start'))


async def delete_bot_backups(server_id: str) -> int:
    """
    Delete all backup files of the configurations managed by the bot. Other backups are not touched.

    Returns:
        int: The number of deleted files.
    """
    path = f'{API_ENDPOINT}{server_id}/backups'
    status, configs = await _request(path)
    if status != 200:
        print(f'backup: failed to get backup configs of {server_id} ({status})')
        return 0

    bot_names = {name for name, _ in KINDS.values()}
    deleted = 0
    async with backup_lock:
        for conf in configs.values():
            if not isinstance(conf, dict) or conf.get('backup_name') not in bot_names:
                continue
            files_path = f'{path}/backup/{conf["backup_id"]}/files'
            status, files = await _request(files_path)
            if status != 200:
                continue
            for file in files.get('backups', []):
                # Crafty lists full paths but expects the file name
                filename = os.path.basename(str(file).replace('\\', '/'))
                status, _ = await _request(files_path, HttpMethod.DELETE, {'filename': filename})
                if status == 200:
                    deleted += 1
                else:
                    print(f'backup: failed to delete {filename} of {server_id} ({status})')
    if deleted:
        print(f'backup: deleted {deleted} bot backups of {server_id}')
    return deleted


async def maintain_server(server_id: str) -> None:
    """
    Keep the configurations of one server up to date and delete backups that are no longer needed.
    """
    if is_excluded(server_id):
        if get('backup.delete_excluded'):
            await delete_bot_backups(server_id)
        return
    await sync_server(server_id)
    days = get('backup.delete_after_days')
    if days > 0 and state.inactive_days(server_id) >= days:
        await delete_bot_backups(server_id)


async def backup_before_start(server_id: str) -> bool:
    """
    Create the backup before a server is started. Returns True if it was created.
    """
    return await run_backup(server_id, 'start', max(get('backup.timeout'), 30))


def mark_started(server_id: str) -> None:
    state.mark_online(server_id)
    state.save()


def _last_due(now: datetime, weekday: int | None = None) -> datetime:
    """
    The most recent scheduled time at or before now (daily, or weekly on the given weekday).
    """
    hour, minute = map(int, get('backup.time').split(':'))
    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if weekday is None:
        if due > now:
            due -= timedelta(days=1)
    else:
        due -= timedelta(days=(due.weekday() - weekday) % 7)
        if due > now:
            due -= timedelta(days=7)
    return due


async def record_activity(servers: list[dict]) -> None:
    """
    Remember which servers are online, so scheduled backups only run for servers that were used.
    """
    stats = await asyncio.gather(*(get_server_stats(server['server_id']) for server in servers))
    changed = False
    for server, server_stats in zip(servers, stats):
        if server_stats and server_stats.get('running'):
            state.mark_online(server['server_id'])
            changed = True
    if changed:
        state.save()


async def run_due_backups(servers: list[dict]) -> None:
    """
    Run the daily and weekly backups that are due, for every server that was online since its last one.
    """
    now = datetime.now(ZoneInfo(get('backup.timezone')))
    schedule = {'daily': _last_due(now), 'weekly': _last_due(now, get('backup.weekday'))}
    for kind, due in schedule.items():
        if get(KINDS[kind][1]) <= 0:
            continue
        last_run = state.data['last_run'].get(kind)
        if last_run is None:
            # first start with backups enabled: begin with the next scheduled time
            state.data['last_run'][kind] = now.timestamp()
            state.save()
            continue
        if last_run >= due.timestamp():
            continue

        print(f'backup: running {kind} backups')
        for server in servers:
            server_id = server['server_id']
            if is_excluded(server_id):
                continue
            if state.was_online_since_backup(server_id, kind):
                await run_backup(server_id, kind, SCHEDULED_TIMEOUT)
            else:
                print(f'backup: skipping {kind} backup of {server["server_name"]}, not online since the last one')
        state.data['last_run'][kind] = time.time()
        state.save()


class BackupScheduler:
    """
    Called once a minute: records which servers are online, keeps the Crafty configurations up to date,
    deletes backups that are no longer needed and runs the scheduled backups.
    """

    def __init__(self):
        self.last_sync = 0.0

    async def tick(self) -> None:
        try:
            servers = await get_servers()
            if servers is None:
                print('backup: failed to get server list, retrying next run')
                return
            await record_activity(servers)
            if not get('backup.enabled'):
                return
            if time.time() - self.last_sync >= SYNC_INTERVAL:
                for server in servers:
                    await maintain_server(server['server_id'])
                self.last_sync = time.time()
            await run_due_backups(servers)
        except Exception:
            # keep the loop alive on unexpected errors
            traceback.print_exc()
