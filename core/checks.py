"""
This module contains the permission checks for the bot commands.
"""

from discord.ext import commands

from core.constants import COMMAND_CHANNEL_ID, CONTROL_ROLE_ID


class WrongChannel(commands.CheckFailure):
    """Raised when a command is used outside the command channel."""

    def __init__(self):
        super().__init__(f'Commands can only be used in <#{COMMAND_CHANNEL_ID}>')


class MissingControlRole(commands.CheckFailure):
    """Raised when a user without the control role tries to control a server."""

    def __init__(self):
        super().__init__(f'You need the <@&{CONTROL_ROLE_ID}> role to do that')


async def command_channel_check(ctx: commands.Context) -> bool:
    """
    Global check: only allow commands in the command channel (if set). The bot owner may use any channel.
    """
    if not COMMAND_CHANNEL_ID or await ctx.bot.is_owner(ctx.author):
        return True
    if ctx.channel.id != COMMAND_CHANNEL_ID:
        raise WrongChannel()
    return True


def control_role():
    """
    Check: only allow users with the control role (if set). The bot owner is always allowed.
    """

    async def predicate(ctx: commands.Context) -> bool:
        if not CONTROL_ROLE_ID or await ctx.bot.is_owner(ctx.author):
            return True
        if ctx.guild is None or not any(role.id == CONTROL_ROLE_ID for role in getattr(ctx.author, 'roles', [])):
            raise MissingControlRole()
        return True

    return commands.check(predicate)
