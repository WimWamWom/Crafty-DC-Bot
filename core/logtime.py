"""
This module puts the time in front of every line the bot prints, so the log shows when something happened.
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo


def _timezone():
    # the config may not be loaded yet when the first lines are printed
    config = getattr(sys.modules.get('core.config'), 'config', None)
    # same as backup.timezone, which defaults to TZ or Europe/Berlin
    name = config['backup.timezone'] if config else os.environ.get('TZ') or 'Europe/Berlin'
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError):
        return None


class TimestampedStream:
    """
    Wraps stdout or stderr and starts every line with [YYYY-MM-DD HH:MM:SS].
    """

    def __init__(self, stream):
        self.stream = stream
        self.line_start = True

    def write(self, text: str) -> int:
        stamp = datetime.now(_timezone()).strftime('[%Y-%m-%d %H:%M:%S] ')
        out = []
        for part in text.splitlines(keepends=True):
            if self.line_start:
                out.append(stamp)
            out.append(part)
            self.line_start = part.endswith('\n')
        self.stream.write(''.join(out))
        return len(text)

    def __getattr__(self, name):
        return getattr(self.stream, name)


def install() -> None:
    if not isinstance(sys.stdout, TimestampedStream):
        sys.stdout = TimestampedStream(sys.stdout)
        sys.stderr = TimestampedStream(sys.stderr)
