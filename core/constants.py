# Network
# HTTP status code for a successful request
from core.config import enabled_value, get

STATUS_SUCCESS = 200

# Main
API_ENDPOINT = '/api/v2/servers/'
# Changing these needs a restart: slash commands are registered for the guild and the web server binds the port
GUILD_ID: int = get('discord.guild_id')
WEB_PORT: int = get('web.port')

# Bot logo (embed author icon, web interface favicon and header, Unraid template icon)
LOGO_URL = 'https://wimwamwom.de/Bilder/mc-bot.png'


# The settings below are read on every use, so changes from the web interface take effect without a restart

def auto_stop_enabled() -> bool:
    return get('auto_stop.enabled')


def auto_stop_idle_time() -> int:
    """
    Time in seconds a server may be empty before auto stop stops it.
    """
    return max(get('auto_stop.idle_minutes'), 1) * 60


def control_role_id() -> int:
    """
    Role that is allowed to start, stop and restart servers (0 = no restriction or switched off).
    """
    return enabled_value('discord.control_role_id')


def command_channel_id() -> int:
    """
    Channel in which the bot accepts commands (0 = all channels or switched off).
    """
    return enabled_value('discord.command_channel_id')


def allowed_servers() -> list[str]:
    """
    Server IDs available in the bot (empty = all).
    """
    return get('servers.allowed')


def status_channel_id() -> int:
    """
    Channel of the status embed (0 = disabled or switched off).
    """
    return enabled_value('status.channel_id')


def status_update_interval() -> int:
    return max(get('status.update_interval'), 10)


def session_enabled() -> bool:
    return get('session.enabled')


def session_channel_id() -> int:
    """
    Channel for server start embeds. Without one they go to the channel of /start, other starts to the command channel.
    """
    return get('session.channel_id') or command_channel_id()


def backup_enabled() -> bool:
    return get('backup.enabled')
