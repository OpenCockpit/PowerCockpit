# Copyright (C) 2018-2026 by xcentaurix
# License: GNU General Public License v3.0


import Screens.Standby
from .Debug import logger
from .Version import VERSION
from . import Standby
from . import ConfigInit  # noqa: F401, pylint: disable=unused-import


def Plugins(**__):
    logger.info("  +++ Version: %s starts...", VERSION)
    Screens.Standby.Standby = Standby.Standby
    Screens.Standby.TryQuitMainloop = Standby.TryQuitMainloop
    descriptors = []
    return descriptors
