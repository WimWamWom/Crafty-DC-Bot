# Network
# HTTP status code for a successful request
from core.config import get

STATUS_SUCCESS = 200

# Main
API_ENDPOINT = '/api/v2/servers/'
GUILD_ID: int = get('discord.guild_id')
AUTO_STOP_ENABLED: bool = get('auto_stop.enabled')
AUTO_STOP_SLEEP_TIME: int = max(get('auto_stop.interval'), 60)

# Permissions (0 = no restriction)
# Role that is allowed to start, stop and restart servers
CONTROL_ROLE_ID: int = get('discord.control_role_id')
# Channel in which the bot accepts commands
COMMAND_CHANNEL_ID: int = get('discord.command_channel_id')
# Server IDs available in the bot (empty = all)
ALLOWED_SERVERS: list[str] = get('servers.allowed')

# Status embed (0 = disabled)
STATUS_CHANNEL_ID: int = get('status.channel_id')
STATUS_UPDATE_INTERVAL: int = max(get('status.update_interval'), 10)

# Bot logo (embed author icon, web interface favicon and header, Unraid template icon)
LOGO_URL = 'https://wimwamwom.de/Bilder/mc-bot.png'

# Web interface
WEB_PORT: int = get('web.port')
