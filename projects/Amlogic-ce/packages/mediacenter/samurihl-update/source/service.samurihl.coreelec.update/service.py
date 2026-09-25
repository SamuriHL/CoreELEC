# -*- coding: utf-8 -*-
"""Background service: periodically checks for new SamuriHL/CoreELEC builds."""
import xbmc
import xbmcaddon

from resources.lib import updater

ADDON = xbmcaddon.Addon()

# Give the box a couple of minutes after boot before hammering the network -
# CoreELEC devices are often still bringing up networking right at startup.
STARTUP_DELAY_SECONDS = 120


def main():
    monitor = xbmc.Monitor()

    if monitor.waitForAbort(STARTUP_DELAY_SECONDS):
        return

    while not monitor.abortRequested():
        try:
            updater.run_check(manual=False)
        except Exception as exc:  # noqa: BLE001 - service loop must never die
            updater.log("Unhandled error during check: {0}".format(exc), xbmc.LOGERROR)

        hours = ADDON.getSettingInt("check_interval_hours") or 12
        interval_seconds = max(hours, 1) * 3600

        if monitor.waitForAbort(interval_seconds):
            break


if __name__ == "__main__":
    main()
