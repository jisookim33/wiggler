from maya import cmds as mc
from enum import IntEnum

import logging
logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


class TimeUnit(IntEnum):
    """
    Enum class of all available time units.
    """

    GAME = 15
    FILM = 24
    PAL = 25
    NTSC = 30
    SHOW = 48
    PALF = 50
    NTSCF = 60


def getFPS():
    """
    Returns the scene's current FPS.

    :rtype: TimeUnit
    """

    timeUnit = mc.currentUnit(query=True, time=True)  # type: str
    return TimeUnit[timeUnit.upper()]
