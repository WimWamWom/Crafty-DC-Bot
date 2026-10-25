# Network
# HTTP status code for a successful request
import os

STATUS_SUCCESS = 200


def _int_env(name: str, default: int = 0) -> int:
    """Read an integer environment variable, falling back to default if unset or empty."""
    value = os.getenv(name, '').strip()
    return int(value) if value else default


# Main
API_ENDPOINT = '/api/v2/servers/'
GUILD_ID: int = _int_env('GUILD_ID')
AUTO_STOP_SLEEP_TIME: int = _int_env('AUTO_STOP_SLEEP_TIME', 1800)

# Permissions (0 = no restriction)
# Role that is allowed to start, stop and restart servers
CONTROL_ROLE_ID: int = _int_env('CONTROL_ROLE_ID')
# Channel in which the bot accepts commands
COMMAND_CHANNEL_ID: int = _int_env('COMMAND_CHANNEL_ID')

# Status embed (0 = disabled)
STATUS_CHANNEL_ID: int = _int_env('STATUS_CHANNEL_ID')
STATUS_UPDATE_INTERVAL: int = _int_env('STATUS_UPDATE_INTERVAL', 60)
