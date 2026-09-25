# -*- coding: utf-8 -*-
"""Background service: periodically checks for new SamuriHL/CoreELEC builds."""
import xbmc

from resources.lib import updater

# Give the box a couple of minutes after boot before hammering the network -
# CoreELEC devices are often still bringing up networking right at startup.
STARTUP_DELAY_SECONDS = 120

# A check put off because something was playing is retried this soon,
# instead of waiting out the whole interval.
DEFERRED_RETRY_SECONDS = 600


def main():
    monitor = xbmc.Monitor()

    if monitor.waitForAbort(STARTUP_DELAY_SECONDS):
        return

    while not monitor.abortRequested():
        completed = True
        try:
            completed = updater.run_check(manual=False)
        except Exception as exc:  # noqa: BLE001 - service loop must never die
            updater.log("Unhandled error during check: {0}".format(exc), xbmc.LOGERROR)

        if completed:
            hours = updater.setting_int("check_interval_hours") or 12
            interval_seconds = max(hours, 1) * 3600
        else:
            interval_seconds = DEFERRED_RETRY_SECONDS

        if monitor.waitForAbort(interval_seconds):
            break


if __name__ == "__main__":
    main()
