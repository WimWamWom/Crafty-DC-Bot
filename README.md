# This Repo was originally created by [Two-Play](https://github.com/Two-Play/Crafty-Discord-bot) <br>I cloned it and made some personal changes for my Use-Case

# Crafty Controller Discord bot
![GitHub License](https://img.shields.io/github/license/Two-Play/Crafty-Discord-bot)
![GitHub top language](https://img.shields.io/github/languages/top/Two-Play/Crafty-Discord-bot)
![GitHub contributors](https://img.shields.io/github/contributors/Two-Play/Crafty-Discord-bot)
[![Codacy Badge](https://app.codacy.com/project/badge/Grade/d5b3f979005e4c52916f7fb741068483)](https://app.codacy.com/gh/Two-Play/Crafty-Discord-bot/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)
[![Codacy Badge](https://app.codacy.com/project/badge/Coverage/d5b3f979005e4c52916f7fb741068483)](https://app.codacy.com/gh/Two-Play/Crafty-Discord-bot/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_coverage)

## Table of Contents

1. [Introduction](#introduction)
2. [Features](#features)
3. [Roadmap](#roadmap)
4. [Installation](#installation)
    - [Requirements](#requirements)
    - [Configuration](#configuration)
    - [Docker](#docker)
    - [Python](#python)
5. [Usage](#usage)
6. [Issues](#issues)
7. [Contributing](#contributing)
8. [Support the Project](#support-the-project)
9. [Donations](#donations)
10. [License](#license)

## Introduction

> [!WARNING]
> This project is still in development and is not yet ready for production use. Please use it at your own risk.

This is a Discord bot that is designed to control the Crafty-Controller-4 server. This is useful if friends want to
start a server and you want to control it from Discord.
The bot is written in Python and uses the Discord.py library to interact with the
Discord API.

### Features

- **Server Status**: Get the status of a server as an embed, including the names of the online players
- **Status board**: A self-updating status message with all servers in a channel
- **Server Start / Stop / Restart**: Stop and restart only work when no players are online
- **Server List**: Get a list of all servers
- **Auto Stop**: Stop servers automatically when nobody is online
- **Permissions**: Restrict commands to one channel and server control to one role
- **Server selection**: Choose which Crafty servers are available in the bot
- **Web interface**: Change all settings in the browser (port 4883)

## Roadmap

- **Server Backup**: Create a backup of the server

## Installation

To install the bot, you will need to have a few things set up first.

### Requirements

#### Server

You should have a Server to deploy this bot. You can use a VPS, local server or a Raspberry Pi.
You can also use your own computer, but it is not recommended for availability reasons.

#### Crafty Controller user

You will need to create a new user (recommended) on the Crafty Controller
server and obtain the user token. You can do this by following these steps:

1. Go to your Crafty Controller server
2. Click on the gear icon in the top right corner
3. Click on "add user" and enter a name for your user (for example, "Crafty Bot")
4. Fill in the required fields, select the desired permissions and click on "Save"
5. Click on the pencil icon next to the user you just created
6. Click on "API Key" and select the following permissions:
    - COMMANDS
    - TERMINAL
    - PLAYERS
7. Enter a name for your user token (for example, "Crafty Bot Token")
8. Click on "Create" to generate the user token
9. Save your user token in a safe place (you will need it later)

#### Discord Bot

You will need to create a new Discord bot and obtain a bot token. You can do this by following these steps:

> [!IMPORTANT]  
> I don't know if the permissions are correct, but you can try it out. If it doesn't work, please let me know.
> You can also use the "ALL" permission, but this is not recommended for security reasons.

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click on "New Application"
3. Enter a name for your bot (for example, "Crafty Bot")
4. Accept the terms and click on "Create"
5. If you want to add an icon to your bot, click on "General Information" in the left-hand menu and then click on "
   Upload Image" under "App Icon"
6. Click on "Bot" in the left-hand menu
7. Under "username", you can change the name of your bot if you wish
8. Enable "Presence Intent", "Server Members Intent" and "Message Content Intent"
9. Disable the "Public Bot" option
10. Click on "Reset Token" and confirm by clicking on "Yes, do it!"
11. "Copy" under "Token" to copy your bot token
12. Save your bot token in a safe place (you will need it later)
13. Click on "OAuth2" in the left-hand menu
14. Under "Scopes", select "bot"
15. Under "Bot Permissions", select
    - View Channels
    - Send Messages
    - Create public threads
    - Use slash commands
    - Read Message History
    - Mention Everyone
16. Click on "Copy" under "OAuth2 URL" to copy the invite URL
17. Paste the invite URL into your web browser
18. Select the server you want to invite the bot to
19. Click on "Authorize"

Congratulations! Your bot has been invited to your server

### Configuration

All settings are stored in `data/config.yaml`. The file is created on the first start and can be edited
by hand or in the **web interface** on port `4883` (`http://<host>:4883`). Saving in the web interface
restarts the bot so the changes take effect.

| Setting | Environment variable | Description |
|---|---|---|
| `crafty.url` | `SERVER_URL` | URL of your Crafty Controller, e.g. `https://your-crafty-server-IP:PORT` (required) |
| `crafty.token` | `CRAFTY_TOKEN` | Crafty API token (required) |
| `discord.token` | `DISCORD_TOKEN` | Discord bot token (required) |
| `discord.guild_id` | `GUILD_ID` | ID of your Discord server, needed for slash commands |
| `discord.command_channel_id` | `COMMAND_CHANNEL_ID` | Only accept commands in this channel (0 = all) |
| `discord.control_role_id` | `CONTROL_ROLE_ID` | Only this role may start, stop and restart servers (0 = everyone) |
| `servers.allowed` | `ALLOWED_SERVERS` | Server IDs available in the bot, comma-separated in the env variable (empty = all) |
| `auto_stop.enabled` | `ENABLE_AUTO_STOP_SERVER` | Stop empty servers automatically |
| `auto_stop.interval` | `AUTO_STOP_SLEEP_TIME` | Check interval in seconds (default 1800). A server is stopped after two checks in a row without players |
| `status.channel_id` | `STATUS_CHANNEL_ID` | Channel for the self-updating status message (0 = off) |
| `status.update_interval` | `STATUS_UPDATE_INTERVAL` | Status update interval in seconds (default 60) |
| `web.port` | `WEB_PORT` | Port of the web interface (default 4883) |
| `web.password` | `WEB_PASSWORD` | Password for the web interface (any user name). Set one if the port is reachable from outside |

Environment variables (or a `.env` file) are only used for settings that are missing in `config.yaml`,
e.g. to fill it on the first start. Once the file exists, it wins. If a required setting is missing, only the
web interface starts so you can finish the setup there.

If you use the status board, the bot needs the "Read Message History" permission in that channel so it can find
its status message again after a restart.

### Docker

A ready-made image is built automatically on every push to `main` and published to the GitHub Container Registry
as `ghcr.io/wimwamwom/crafty-dc-bot:latest`. Run it with a volume for the config and the web interface port:

```bash
docker run -d --name crafty-bot -p 4883:4883 -v /path/to/data:/usr/src/app/data ghcr.io/wimwamwom/crafty-dc-bot:latest
```

To build it yourself instead, run `docker build -t crafty-discord-bot .` and use `crafty-discord-bot` as the image.

Then open `http://<host>:4883` and enter your tokens. You can also pass the settings as environment variables
(`-e DISCORD_TOKEN=... -e CRAFTY_TOKEN=... -e SERVER_URL=...`) for the first start.

Or with `docker-compose.yml`:

```yaml
services:
  crafty-bot:
    image: ghcr.io/wimwamwom/crafty-dc-bot:latest
    container_name: crafty-bot
    ports:
      - "4883:4883"
    volumes:
      - ./data:/usr/src/app/data
    restart: unless-stopped
```

For Unraid there is a template in `unraid-app.xml`.

### Python

You need Python 3.10 or higher.

```bash
git clone https://github.com/WimWamWom/Crafty-DC-Bot.git
cd Crafty-DC-Bot
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python core/main.py
```

Then open `http://localhost:4883` to configure the bot, or copy `.env.example` to `.env` and fill in the values
before the first start.

#### Update

```bash
cd Crafty-DC-Bot
git pull
pip install -r requirements.txt
```

## Usage

All commands work as slash commands (`/stats`) and with the `>` prefix (`>stats <server_id>`).
Slash commands need `discord.guild_id` and are synced automatically when the bot starts.
With slash commands, the server name can be picked from a list.

| Command | Description |
|---|---|
| `/list` | List all servers with ID, IP and port |
| `/stats <server>` | Status, players, version, CPU and RAM of a server |
| `/start <server>` | Start a server (control role) |
| `/stop <server>` | Stop a server if no players are online (control role) |
| `/restart <server>` | Restart a server if no players are online (control role) |
| `/sync` | Sync slash commands again (bot owner only) |
| `>help` | List all commands |

The bot owner can use all commands in every channel, regardless of the channel and role settings.

## Issues

If you encounter any issues while using the bot, please report them on the
[GitHub Issues](https://github.com/Two-Play/Crafty-Discord-bot/issues) page.

## Contributing

If you would like to contribute to the project, please follow these steps:

1. Fork the repository
2. Create a new branch (`git checkout -b feature`)
3. Make your changes
4. Commit your changes (`git commit -am 'Add new feature'`)
5. Push to the branch (`git push origin feature`)
6. Create a new Pull Request
7. Wait for your Pull Request to be reviewed
8. Once your Pull Request is approved, it will be merged into the main branch
9. Congratulations! You have successfully contributed to the project

Thank you for your contribution!

If you have any questions, please feel free to reach out to us

## Support the Project

If you would like to support the project, you can do so by:

- Giving the project a star on GitHub
- Sharing the project with others
- Contributing to the project
- Donating to the project

## Donations

If you would like to donate to the project, you can do so using the following methods:

| Platform                                                                                                                             | Link                                                                    | QR Code                                                                                                                                                                                           |
|--------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| ![Buy Me A Coffee Badge](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-FD0?logo=buymeacoffee&logoColor=000&style=for-the-badge) | [Buy Me a Coffee](https://www.buymeacoffee.com/TwoPlay)                 | ![Buy Me a Coffee QR Code](https://api.qrserver.com/v1/create-qr-code/?color=000000&bgcolor=FFFFFF&data=https://www.buymeacoffee.com/TwoPlay&qzone=1&margin=0&size=150x150&ecc=L)                 |
| ![PayPal Badge](https://img.shields.io/badge/PayPal-003087?logo=paypal&logoColor=fff&style=for-the-badge)                            | [PayPal](https://www.paypal.com/donate/?hosted_button_id=RQAUT43DDLTJG) | ![PayPal QR Code](https://api.qrserver.com/v1/create-qr-code/?color=000000&bgcolor=FFFFFF&data=https://www.paypal.com/donate/?hosted_button_id=RQAUT43DDLTJG&qzone=1&margin=0&size=150x150&ecc=L) |

### Cryptocurrency Donations

You can click on the QR code to show a larger version of the QR code. GitHub does not support displaying large images in
the README file.

| Cryptocurrency                                                                                                  | Abbreviation | <div style="min-width:150px">QR-Code</div>                                                                                                                                                                                          | Address                                                                                           |
|:----------------------------------------------------------------------------------------------------------------|:-------------|:------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:--------------------------------------------------------------------------------------------------|
| ![Bitcoin Badge](https://img.shields.io/badge/Bitcoin-F7931A?logo=bitcoin&logoColor=fff&style=for-the-badge)    | BTC          | <img src="https://api.qrserver.com/v1/create-qr-code/?color=000000&bgcolor=FFFFFF&data=bc1qk2xrz4mffeyh9dv8jm42vlejgmzft3adnweeqy&qzone=1&margin=0&size=150x150&ecc=L" style="min-width:150px" alr="Bitcoin QR-Code">               | `bc1qk2xrz4mffeyh9dv8jm42vlejgmzft3adnweeqy`                                                      |
| ![Ethereum Badge](https://img.shields.io/badge/Ethereum-3C3C3D?logo=ethereum&logoColor=fff&style=for-the-badge) | ETH          | ![Ethereum QR Code](https://api.qrserver.com/v1/create-qr-code/?color=000000&bgcolor=FFFFFF&data=0xBA615b7341C0d9aB4337dE4927B87e9E30fbE0b9&qzone=1&margin=0&size=150x150&ecc=L)                                                    | `0xBA615b7341C0d9aB4337dE4927B87e9E30fbE0b9`                                                      |
| ![Litecoin Badge](https://img.shields.io/badge/Litecoin-A6A9AA?logo=litecoin&logoColor=fff&style=for-the-badge) | LTC          | ![Litecoin QR Code](https://api.qrserver.com/v1/create-qr-code/?color=000000&bgcolor=FFFFFF&data=LNTn2u6svYMYswuwPSWTj41iXnxe4tP99i&qzone=1&margin=0&size=150x150&ecc=L)                                                            | `LNTn2u6svYMYswuwPSWTj41iXnxe4tP99i`                                                              |
| ![Monero Badge](https://img.shields.io/badge/Monero-F60?logo=monero&logoColor=fff&style=for-the-badge)          | XMR          | ![Monero QR Code](https://api.qrserver.com/v1/create-qr-code/?color=000000&bgcolor=FFFFFF&data=41hZYQV5uDzfiLCusRAxARST3hfTzGv7RNRyB92G1RZw64pvEQqwDo94zZHVxfvcmncLU1ockvJxbZBQToPqqDtBAor97sU&qzone=1&margin=0&size=150x150&ecc=L) | `41hZYQV5uDzfiLCusRAxARST3hfTzGv7RNRyB92G1RZw64pvEQqwDo94zZHVxfvcmncLU1ockvJxbZBQToPqqDtBAor97sU` |

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details.
