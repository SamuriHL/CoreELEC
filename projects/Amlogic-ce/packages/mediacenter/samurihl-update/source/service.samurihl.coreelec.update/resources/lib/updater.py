# -*- coding: utf-8 -*-
"""
Core logic for checking/downloading SamuriHL/CoreELEC builds.
Shared by service.py (background loop) and default.py (manual "Check now").
"""
import json
import hashlib
import os
import re
import urllib.request
import urllib.error

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
ADDON_NAME = ADDON.getAddonInfo("name")
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))

GITHUB_API = "https://api.github.com/repos/SamuriHL/CoreELEC/releases"
UPDATE_DIR = "/storage/.update"
STATE_FILE = os.path.join(PROFILE, "state.json")

# CoreELEC build strings from this fork embed a 14-digit YYYYMMDDHHMMSS
# timestamp (e.g. ..._20260803114520). We use that to compare "newer than"
# rather than trying to parse full version strings, since that's the one
# thing guaranteed to be both in the installed build string and the tag.
TIMESTAMP_RE = re.compile(r"(\d{14})")


def log(msg, level=xbmc.LOGINFO):
    xbmc.log("[{0}] {1}".format(ADDON_ID, msg), level=level)


def _(string_id):
    return ADDON.getLocalizedString(string_id)


def notify(message, icon=xbmcgui.NOTIFICATION_INFO, time_ms=8000):
    xbmcgui.Dialog().notification(_(30020), message, icon, time_ms)


# ---------------------------------------------------------------------------
# Installed-version detection
# ---------------------------------------------------------------------------

def get_installed_timestamp():
    """Read /etc/os-release and pull the 14-digit build timestamp out of it."""
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            match = TIMESTAMP_RE.search(content)
            if match:
                return match.group(1)
        except OSError as exc:
            log("Could not read {0}: {1}".format(path, exc), xbmc.LOGWARNING)
    return None


# ---------------------------------------------------------------------------
# State (what we last saw / last notified about / last downloaded)
# ---------------------------------------------------------------------------

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        if not os.path.isdir(PROFILE):
            os.makedirs(PROFILE)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError as exc:
        log("Could not write state file: {0}".format(exc), xbmc.LOGWARNING)


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

def _http_get_json(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "{0}/{1}".format(ADDON_ID, ADDON.getAddonInfo("version")),
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_release(release):
    """Turn one GitHub API release object into our normalized dict, or None
    if it's not usable (draft, no parseable timestamp, no .tar asset)."""
    if release.get("draft"):
        return None
    tag = release.get("tag_name", "")
    ts_match = TIMESTAMP_RE.search(tag) or TIMESTAMP_RE.search(release.get("name", ""))
    if not ts_match:
        return None
    timestamp = ts_match.group(1)

    tar_asset = None
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".tar"):
            tar_asset = asset
            break
    if not tar_asset:
        return None

    body = release.get("body", "") or ""
    sha256 = _extract_checksum(body, tar_asset["name"])

    return {
        "tag": tag,
        "timestamp": timestamp,
        "tar_name": tar_asset["name"],
        "tar_url": tar_asset["browser_download_url"],
        "tar_size": tar_asset.get("size", 0),
        "sha256": sha256,
        "body": body,
        "prerelease": bool(release.get("prerelease")),
        "published_at": release.get("published_at", ""),
    }


def fetch_latest_release():
    """Return a dict describing the newest usable release, or None."""
    releases = _http_get_json(GITHUB_API)
    for release in releases:
        parsed = _parse_release(release)
        if parsed:
            return parsed
    return None


def fetch_releases_list(limit=20):
    """Return up to `limit` usable releases, newest first."""
    releases = _http_get_json(GITHUB_API)
    parsed = []
    for release in releases:
        item = _parse_release(release)
        if item:
            parsed.append(item)
        if len(parsed) >= limit:
            break
    return parsed


def _extract_checksum(body, filename):
    """Pull a matching sha256 out of the release notes' checksum block, if present."""
    pattern = re.compile(
        r"([0-9a-fA-F]{64})\s+\**" + re.escape(filename) + r"\**"
    )
    match = pattern.search(body)
    return match.group(1).lower() if match else None


# ---------------------------------------------------------------------------
# Download + verify
# ---------------------------------------------------------------------------

def human_size(num_bytes):
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024.0:
            return "{0:.1f} {1}".format(num_bytes, unit)
        num_bytes /= 1024.0
    return "{0:.1f} TB".format(num_bytes)


def download_and_verify(release, progress_dialog=None):
    """
    Downloads release['tar_url'] into /storage/.update, verifying sha256
    if one was found in the release notes and verification is enabled.
    Returns True on success, False on failure. Cleans up on any failure.
    """
    if not os.path.isdir(UPDATE_DIR):
        try:
            os.makedirs(UPDATE_DIR)
        except OSError as exc:
            log("Cannot create {0}: {1}".format(UPDATE_DIR, exc), xbmc.LOGERROR)
            return False

    # Clear out any previously staged update tars so only one is ever pending.
    for existing in os.listdir(UPDATE_DIR):
        if existing.endswith(".tar"):
            try:
                os.remove(os.path.join(UPDATE_DIR, existing))
            except OSError:
                pass

    dest_path = os.path.join(UPDATE_DIR, release["tar_name"])
    tmp_path = dest_path + ".part"

    req = urllib.request.Request(
        release["tar_url"],
        headers={"User-Agent": "{0}/{1}".format(ADDON_ID, ADDON.getAddonInfo("version"))},
    )

    hasher = hashlib.sha256()
    total = release.get("tar_size") or 0
    written = 0

    try:
        with urllib.request.urlopen(req, timeout=30) as resp, open(tmp_path, "wb") as out:
            chunk_size = 1024 * 1024
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
                hasher.update(chunk)
                written += len(chunk)
                if progress_dialog is not None:
                    percent = int(written * 100 / total) if total else 0
                    # DialogProgressBG is a non-interactive background bar -
                    # it has no Cancel button and no iscanceled() method, so
                    # there is nothing here for the user to cancel.
                    progress_dialog.update(
                        percent,
                        message="{0} / {1}".format(human_size(written), human_size(total)) if total else human_size(written),
                    )
    except (urllib.error.URLError, OSError) as exc:
        log("Download failed: {0}".format(exc), xbmc.LOGERROR)
        _cleanup(tmp_path)
        return False

    if ADDON.getSettingBool("verify_checksum") and release.get("sha256"):
        digest = hasher.hexdigest().lower()
        if digest != release["sha256"]:
            log(
                "Checksum mismatch: expected {0}, got {1}".format(release["sha256"], digest),
                xbmc.LOGERROR,
            )
            _cleanup(tmp_path)
            return False

    try:
        os.replace(tmp_path, dest_path)
    except OSError as exc:
        log("Could not finalize download: {0}".format(exc), xbmc.LOGERROR)
        _cleanup(tmp_path)
        return False

    return True


def _cleanup(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Manual browse/pick a specific release
# ---------------------------------------------------------------------------

def browse_and_install():
    """Let the user pick any recent release from a list and stage it,
    instead of always taking the newest one."""
    # Not all Kodi builds ship xbmcgui.DialogBusy (e.g. CoreELEC's bundled
    # Python API on some versions doesn't), so drive the busy overlay
    # directly through the window builtin instead - that's supported
    # everywhere.
    xbmc.executebuiltin("ActivateWindow(busydialognocancel)")
    try:
        installed_ts = get_installed_timestamp()
        try:
            releases = fetch_releases_list(limit=20)
        except (urllib.error.URLError, ValueError) as exc:
            log("Fetching release list failed: {0}".format(exc), xbmc.LOGERROR)
            notify(_(30024), xbmcgui.NOTIFICATION_ERROR)
            return
    finally:
        xbmc.executebuiltin("Dialog.Close(busydialognocancel)")

    if not releases:
        notify(_(30030), xbmcgui.NOTIFICATION_WARNING)
        return

    labels = []
    for r in releases:
        marker = ""
        if installed_ts and r["timestamp"] == installed_ts:
            marker = "  [{0}]".format(_(30041))
        elif installed_ts and r["timestamp"] < installed_ts:
            marker = "  [{0}]".format(_(30042))
        size = human_size(r["tar_size"]) if r["tar_size"] else "?"
        checksum_flag = "" if r["sha256"] else "  [{0}]".format(_(30043))
        labels.append("{0}  ({1}){2}{3}".format(r["tag"], size, checksum_flag, marker))

    dialog = xbmcgui.Dialog()
    index = dialog.select(_(30040), labels)
    if index < 0:
        return

    chosen = releases[index]

    if not dialog.yesno(
        _(30020),
        _(30044).format(chosen["tag"]),
        yeslabel=_(30045),
        nolabel=_(30034),
    ):
        return

    progress = xbmcgui.DialogProgressBG()
    progress.create(_(30020), _(30025).format(chosen["tar_name"]))
    try:
        ok = download_and_verify(chosen, progress_dialog=progress)
    finally:
        progress.close()

    if not ok:
        notify(_(30031), xbmcgui.NOTIFICATION_ERROR)
        return

    state = load_state()
    state["downloaded_timestamp"] = chosen["timestamp"]
    save_state(state)

    if dialog.yesno(_(30020), _(30028), yeslabel=_(30033), nolabel=_(30034)):
        xbmc.executebuiltin("Reboot")


# ---------------------------------------------------------------------------
# High-level entry point used by both service.py and default.py
# ---------------------------------------------------------------------------

def run_check(manual=False):
    """
    Runs one check/update cycle.
    manual=True means the user triggered this from the addon menu, so we
    show progress/result dialogs even when there's nothing new.
    """
    if not manual and not ADDON.getSettingBool("enabled"):
        return

    progress = xbmcgui.DialogProgressBG() if manual else None
    if progress:
        progress.create(_(30020), _(30021))

    try:
        installed_ts = get_installed_timestamp()
        try:
            release = fetch_latest_release()
        except (urllib.error.URLError, ValueError) as exc:
            log("Update check failed: {0}".format(exc), xbmc.LOGERROR)
            if manual:
                notify(_(30024), xbmcgui.NOTIFICATION_ERROR)
            return

        if release is None:
            log("No suitable release with a .tar asset was found", xbmc.LOGWARNING)
            if manual:
                notify(_(30030), xbmcgui.NOTIFICATION_WARNING)
            return

        state = load_state()

        is_newer = installed_ts is None or release["timestamp"] > installed_ts

        if not is_newer:
            log("Up to date: installed={0} latest={1}".format(installed_ts, release["timestamp"]))
            if manual:
                notify(_(30023).format(release["tag"]))
            return

        already_downloaded = state.get("downloaded_timestamp") == release["timestamp"]
        already_notified = state.get("notified_timestamp") == release["timestamp"]

        if ADDON.getSettingBool("auto_download") and not already_downloaded:
            if progress:
                progress.update(0, message=_(30025).format(release["tar_name"]))
            ok = download_and_verify(release, progress_dialog=progress)
            if not ok:
                notify(_(30031), xbmcgui.NOTIFICATION_ERROR)
                return

            state["downloaded_timestamp"] = release["timestamp"]
            save_state(state)

            if ADDON.getSettingBool("auto_reboot"):
                notify(_(30029))
                xbmc.sleep(3000)
                xbmc.executebuiltin("Reboot")
            else:
                if xbmcgui.Dialog().yesno(
                    _(30020),
                    _(30028),
                    yeslabel=_(30033),
                    nolabel=_(30034),
                ):
                    xbmc.executebuiltin("Reboot")
            return

        if already_downloaded:
            if manual:
                notify(_(30029))
            return

        # Notify-only path
        if manual or not (ADDON.getSettingBool("notify_only_once_per_build") and already_notified):
            notify(_(30022).format(release["tag"]))
            state["notified_timestamp"] = release["timestamp"]
            save_state(state)

    finally:
        if progress:
            progress.close()
