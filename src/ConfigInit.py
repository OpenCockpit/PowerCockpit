# Copyright (C) 2018-2026 by xcentaurix
# License: GNU General Public License v3.0


from Components.config import config, ConfigYesNo, ConfigSelection, ConfigSubsection
from .Debug import logger


logger.info("...")
if not hasattr(config.plugins, "powercockpit"):
    config.plugins.powercockpit = ConfigSubsection()
# Show the message that names the reason when the box goes to standby to wait for its activities before a shutdown.
# Not in a setup screen: change it in /etc/enigma2/settings while Enigma2 is stopped.
config.plugins.powercockpit.show_idle_msg = ConfigYesNo(default=True)

# config.usage.power only exists on OpenViX (Components/UsageConfig.py); openATV
# has no equivalent boot-state-recovery feature, so register it here too when
# missing so Standby.py's lastPowerState() can track state on both forks.
if not hasattr(config.usage, "power"):
    config.usage.power = ConfigSubsection()
    config.usage.power.last_known_state = ConfigSelection(default="normal", choices=[
        "normal",
        "standby",
        "deep",
    ])
