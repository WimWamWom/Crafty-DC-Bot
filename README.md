# Crafty Controller Discord bot

A Discord bot to control servers on [Crafty Controller 4](https://craftycontrol.com/) from Discord.
Based on [Two-Play/Crafty-Discord-bot](https://github.com/Two-Play/Crafty-Discord-bot), adapted for my own use.

## Features

- Server status as an embed with a dropdown for every server, including the names of online players
- Start, stop and restart servers (stop and restart only when nobody is online)
- Self-updating status board with all servers in one channel
- Auto stop for empty servers
- Commands limited to one channel, server control limited to one role
- Choose which Crafty servers the bot shows
- Web interface on port 4883 for all settings

## Commands

All commands are slash commands and are synced automatically when the bot starts.
They also work with the `>` prefix (`>stats`).

| Command | Description |
|---|---|
| `/stats` | Status of all servers, with a dropdown to show players, version, CPU and RAM of one server |
| `/start <server>` | Start a server (control role) |
| `/stop <server>` | Stop a server if no players are online (control role) |
| `/restart <server>` | Restart a server if no players are online (control role) |
| `/help` | List all commands |

The bot owner can use all commands in every channel, regardless of the channel and role settings.

## Setup

### Crafty API token

Create a user for the bot in Crafty (gear icon → add user), then open the user, go to "API Key" and create a token
with the permissions `COMMANDS`, `TERMINAL` and `PLAYERS`.

### Discord bot

1. Create an application in the [Discord Developer Portal](https://discord.com/developers/applications)
2. Under "Bot": enable "Message Content Intent", disable "Public Bot" and copy the token
3. Under "OAuth2": select the scope `bot` and the permissions View Channels, Send Messages,
   Read Message History and Use Slash Commands, then open the generated URL and invite the bot

### Docker

The image is built on every push to `main` and published as `ghcr.io/wimwamwom/crafty-dc-bot:latest`.

```yaml
services:
  crafty-bot:
    image: ghcr.io/wimwamwom/crafty-dc-bot:latest
    container_name: crafty-bot
    ports:
      - "4883:4883"
    volumes:
      - ./data:/data
    restart: unless-stopped
```

Then open `http://<host>:4883` and enter your tokens. For Unraid there is a template in `unraid-app.xml`.

### Python

Requires Python 3.10 or higher.

```bash
git clone https://github.com/WimWamWom/Crafty-DC-Bot.git
cd Crafty-DC-Bot
pip install -r requirements.txt
python core/main.py
```

## Configuration

All settings are stored in `data/config.yaml`. The file is created on the first start and can be edited by hand
or in the web interface (`http://<host>:4883`). Saving in the web interface restarts the bot.
Environment variables (or a `.env` file, see `.env.example`) are only used for settings missing in the file.
If a required setting is missing, only the web interface starts.

| Setting | Environment variable | Description |
|---|---|---|
| `crafty.url` | `SERVER_URL` | URL of your Crafty Controller (required) |
| `crafty.token` | `CRAFTY_TOKEN` | Crafty API token (required) |
| `discord.token` | `DISCORD_TOKEN` | Discord bot token (required) |
| `discord.guild_id` | `GUILD_ID` | ID of your Discord server, needed for slash commands |
| `discord.command_channel_enabled` | `COMMAND_CHANNEL_ENABLED` | Switch: only accept commands in one channel |
| `discord.command_channel_id` | `COMMAND_CHANNEL_ID` | The command channel |
| `discord.control_role_enabled` | `CONTROL_ROLE_ENABLED` | Switch: only one role may start, stop and restart |
| `discord.control_role_id` | `CONTROL_ROLE_ID` | The control role |
| `servers.allowed` | `ALLOWED_SERVERS` | Server IDs shown in the bot, comma-separated (empty = all) |
| `auto_stop.enabled` | `ENABLE_AUTO_STOP_SERVER` | Stop empty servers automatically |
| `auto_stop.interval` | `AUTO_STOP_SLEEP_TIME` | Check interval in seconds (default 1800), stop after two empty checks in a row |
| `status.enabled` | `STATUS_ENABLED` | Switch: show the self-updating status board |
| `status.channel_id` | `STATUS_CHANNEL_ID` | Channel for the status board |
| `status.update_interval` | `STATUS_UPDATE_INTERVAL` | Status board update interval in seconds (default 60) |
| `web.port` | `WEB_PORT` | Port of the web interface (default 4883) |
| `web.password` | `WEB_PASSWORD` | Password for the web interface (any user name) |

## License

MIT, see [LICENSE.md](LICENSE.md).
