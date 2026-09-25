# -*- coding: utf-8 -*-
"""Manual entry point - run from Add-ons > Program add-ons > SamuriHL CoreELEC Update Checker."""
import xbmcgui

from resources.lib import updater

if __name__ == "__main__":
    dialog = xbmcgui.Dialog()
    choice = dialog.select(
        updater._(30020),
        [updater._(30046), updater._(30040)],
    )
    if choice == 0:
        updater.run_check(manual=True)
    elif choice == 1:
        updater.browse_and_install()
