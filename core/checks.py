"""
This module contains the permission checks for the bot commands.
"""

from discord.ext import commands

from core.constants import command_channel_id, control_role_id, panel_channel_ids


class WrongChannel(commands.CheckFailure):
    """Raised when a command is used outside the command channel."""

    def __init__(self):
        super().__init__(f'Commands can only be used in <#{command_channel_id()}>')


class MissingControlRole(commands.CheckFailure):
    """Raised when a user without the control role tries to control a server."""

    def __init__(self):
        super().__init__(f'You need the <@&{control_role_id()}> role to do that')


class PanelChannel(commands.CheckFailure):
    """Raised when a command is used in the channel of a server panel."""

    def __init__(self):
        channel_id = command_channel_id()
        where = f' in <#{channel_id}>' if channel_id else ' in another channel'
        super().__init__(f'This channel only has the server buttons, use commands{where}')


async def command_channel_check(ctx: commands.Context) -> bool:
    """
    Global check: only allow commands in the command channel (if set) and never in a panel channel.
    The bot owner may use any other channel.
    """
    # panel channels only hold the panels, also for the bot owner
    if ctx.channel.id in panel_channel_ids():
        raise PanelChannel()
    channel_id = command_channel_id()
    if not channel_id or await ctx.bot.is_owner(ctx.author):
        return True
    if ctx.channel.id != channel_id:
        raise WrongChannel()
    return True


def control_role():
    """
    Check: only allow users with the control role (if set). The bot owner is always allowed.
    """

    async def predicate(ctx: commands.Context) -> bool:
        role_id = control_role_id()
        if not role_id or await ctx.bot.is_owner(ctx.author):
            return True
        if ctx.guild is None or not any(role.id == role_id for role in getattr(ctx.author, 'roles', [])):
            raise MissingControlRole()
        return True

    return commands.check(predicate)
