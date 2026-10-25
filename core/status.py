"""
This module keeps a self-updating status message with all servers in a channel.
"""

import asyncio

import discord

from core.embeds import STATUS_FOOTER, status_embed
from core.server import get_server_stats, get_servers


class StatusBoard:
    """
    Posts the status embed once and edits the same message on every update.
    """

    def __init__(self, bot: discord.Client, channel_id):
        """
        Args:
            channel_id: Function that returns the status channel (0 = off), read on every update.
        """
        self.bot = bot
        self._channel_id = channel_id
        self.channel_id = 0
        self.message: discord.Message | None = None

    async def _get_channel(self) -> discord.abc.Messageable:
        channel = self.bot.get_channel(self.channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(self.channel_id)
        return channel

    async def _find_existing_message(self, channel) -> discord.Message | None:
        """
        Find the status message from a previous run, so the bot does not post a new one after each restart.
        """
        async for message in channel.history(limit=50):
            if (message.author.id == self.bot.user.id and message.embeds
                    and message.embeds[0].footer.text == STATUS_FOOTER):
                return message
        return None

    async def update(self) -> None:
        channel_id = self._channel_id()
        if channel_id != self.channel_id:
            # switched off or moved to another channel: look for the message there
            self.channel_id = channel_id
            self.message = None
        if not channel_id:
            return
        servers = await get_servers()
        if servers is None:
            print('status: failed to get server list')
            return
        stats = await asyncio.gather(*(get_server_stats(server['server_id']) for server in servers))
        embed = status_embed(list(zip(servers, stats)))

        channel = await self._get_channel()
        if self.message is None:
            self.message = await self._find_existing_message(channel)
        if self.message is not None:
            try:
                await self.message.edit(embed=embed)
                return
            except discord.NotFound:
                self.message = None
        self.message = await channel.send(embed=embed)
