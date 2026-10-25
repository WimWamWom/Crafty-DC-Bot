"""
This module contains the interactive Discord views (dropdowns) of the bot.
"""

import discord

from core.embeds import new_embed, server_stats_embed
from core.server import get_server_stats

# Discord allows at most 25 options in a dropdown
MAX_OPTIONS = 25


class ServerSelect(discord.ui.Select):
    """
    Dropdown with all servers. Choosing a server shows its stats in the same message.
    """

    def __init__(self, servers: list[dict]):
        self.names = {server['server_id']: server['server_name'] for server in servers[:MAX_OPTIONS]}
        options = [discord.SelectOption(label=name[:100], value=server_id)
                   for server_id, name in self.names.items()]
        super().__init__(placeholder='Choose a server', options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        server_id = self.values[0]
        # keep the chosen server visible in the dropdown
        for option in self.options:
            option.default = option.value == server_id

        await interaction.response.defer()
        stats = await get_server_stats(server_id)
        if stats is None:
            embed = new_embed(title=self.names[server_id], description='failed to get server stats',
                              color=discord.Color.light_grey())
        else:
            embed = server_stats_embed(self.names[server_id], stats)
        await interaction.edit_original_response(embed=embed, view=self.view)


class ServerStatsView(discord.ui.View):
    """
    View for the stats command. Only the user who used the command can choose a server.
    """

    def __init__(self, servers: list[dict], user_id: int, timeout: float = 600):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.message: discord.Message | None = None
        self.add_item(ServerSelect(servers))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message('Use `/stats` yourself to choose a server', ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        # disable the dropdown so it does not fail silently after the timeout
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
