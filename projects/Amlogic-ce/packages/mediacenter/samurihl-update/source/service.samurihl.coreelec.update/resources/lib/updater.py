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
ADDON_ICON = ADDON.getAddonInfo("icon")
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))

GITHUB_API = "https://api.github.com/repos/SamuriHL/CoreELEC/releases"
UPDATE_DIR = "/storage/.update"
STATE_FILE = os.path.join(PROFILE, "state.json")

# The only builder this add-on updates. Any other build (official CoreELEC,
# another fork) is never offered an update automatically.
BUILDER_NAME = "samurihl"

# CoreELEC build strings from this fork embed a 14-digit YYYYMMDDHHMMSS
# timestamp (e.g. ..._20260803114520). We use that to compare "newer than"
# rather than trying to parse full version strings, since that's the one
# thing guaranteed to be both in the installed build string and the tag.
TIMESTAMP_RE = re.compile(r"(\d{14})")
SHA256_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")


class DownloadAborted(Exception):
    """Raised when an unattended download stops because playback started."""


def log(msg, level=xbmc.LOGINFO):
    xbmc.log("[{0}] {1}".format(ADDON_ID, msg), level=level)


def _(string_id):
    return ADDON.getLocalizedString(string_id)


def setting_bool(setting_id):
    # A fresh Addon() every read, so a change made in the settings dialog is
    # seen by the long-running service without restarting Kodi.
    return xbmcaddon.Addon().getSettingBool(setting_id)


def setting_int(setting_id):
    return xbmcaddon.Addon().getSettingInt(setting_id)


def notify(message, icon=None, time_ms=8000):
    xbmcgui.Dialog().notification(_(30020), message, icon or ADDON_ICON, time_ms)


def is_playing():
    return xbmc.Player().isPlaying()


# ---------------------------------------------------------------------------
# Installed-build detection
# ---------------------------------------------------------------------------

def get_os_release():
    """Return /etc/os-release as a dict (quotes stripped), or {}."""
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            if not os.path.exists(path):
                continue
            fields = {}
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    key, sep, value = line.strip().partition("=")
                    if sep:
                        fields[key] = value.strip('"')
            return fields
        except OSError as exc:
            log("Could not read {0}: {1}".format(path, exc), xbmc.LOGWARNING)
    return {}


def get_installed_build():
    """Return (is_samurihl, timestamp, distro_arch) for the running build."""
    fields = get_os_release()
    is_samurihl = fields.get("BUILDER_NAME") == BUILDER_NAME
    match = TIMESTAMP_RE.search(fields.get("VERSION", ""))
    return is_samurihl, match.group(1) if match else None, fields.get("DISTRO_ARCH")


def get_installed_timestamp():
    return get_installed_build()[1]


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

def _http_request(url, accept=None):
    headers = {"User-Agent": "{0}/{1}".format(ADDON_ID, ADDON.getAddonInfo("version"))}
    if accept:
        headers["Accept"] = accept
    return urllib.request.Request(url, headers=headers)


def _http_get_json(url):
    with urllib.request.urlopen(_http_request(url, "application/vnd.github+json"), timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_release(release, distro_arch=None):
    """Turn one GitHub API release object into our normalized dict, or None
    if it's not usable (draft, no parseable timestamp, no .tar asset for this
    box's DISTRO_ARCH)."""
    if release.get("draft"):
        return None
    tag = release.get("tag_name", "")
    ts_match = TIMESTAMP_RE.search(tag) or TIMESTAMP_RE.search(release.get("name", ""))
    if not ts_match:
        return None
    timestamp = ts_match.group(1)

    assets = release.get("assets", [])
    tar_asset = None
    for asset in assets:
        name = asset.get("name", "")
        if not name.endswith(".tar"):
            continue
        # Update tars are named CoreELEC-<DISTRO_ARCH>-<version>.tar; never
        # stage a tar built for a different SoC family.
        if distro_arch and "-{0}-".format(distro_arch) not in name:
            continue
        tar_asset = asset
        break
    if not tar_asset:
        return None

    sha_asset = None
    for asset in assets:
        if asset.get("name") == tar_asset["name"] + ".sha256":
            sha_asset = asset
            break

    body = release.get("body", "") or ""
    sha256 = _extract_checksum(body, tar_asset["name"])

    return {
        "tag": tag,
        "timestamp": timestamp,
        "tar_name": tar_asset["name"],
        "tar_url": tar_asset["browser_download_url"],
        "tar_size": tar_asset.get("size", 0),
        "sha256": sha256,
        "sha256_url": sha_asset["browser_download_url"] if sha_asset else None,
        "body": body,
        "prerelease": bool(release.get("prerelease")),
        "published_at": release.get("published_at", ""),
    }


def fetch_latest_release(distro_arch=None):
    """Return a dict describing the newest usable release, or None."""
    releases = _http_get_json(GITHUB_API)
    for release in releases:
        parsed = _parse_release(release, distro_arch)
        if parsed:
            return parsed
    return None


def fetch_releases_list(limit=20, distro_arch=None):
    """Return up to `limit` usable releases, newest first."""
    releases = _http_get_json(GITHUB_API)
    parsed = []
    for release in releases:
        item = _parse_release(release, distro_arch)
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


def _fetch_sidecar_checksum(url):
    """Read the published <tar>.sha256 asset. Its filename column predates the
    EXPERIMENTAL rename, so only the hash itself is used."""
    try:
        with urllib.request.urlopen(_http_request(url), timeout=20) as resp:
            text = resp.read(4096).decode("utf-8", errors="ignore")
    except (urllib.error.URLError, OSError) as exc:
        log("Could not fetch checksum file {0}: {1}".format(url, exc), xbmc.LOGWARNING)
        return None
    match = SHA256_RE.search(text)
    return match.group(1).lower() if match else None


def resolve_checksum(release):
    """Checksum from the release notes, else from the .sha256 asset."""
    if not release.get("sha256") and release.get("sha256_url"):
        release["sha256"] = _fetch_sidecar_checksum(release["sha256_url"])
    return release.get("sha256")


# ---------------------------------------------------------------------------
# Download + verify
# ---------------------------------------------------------------------------

def human_size(num_bytes):
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024.0:
            return "{0:.1f} {1}".format(num_bytes, unit)
        num_bytes /= 1024.0
    return "{0:.1f} TB".format(num_bytes)


def download_and_verify(release, progress_dialog=None, stop_on_playback=False):
    """
    Downloads release['tar_url'] into /storage/.update, verifying sha256
    when verification is enabled. Returns True on success, False on failure.
    Any update already staged is left in place until the new one has fully
    downloaded and verified. With stop_on_playback the download is abandoned
    (DownloadAborted) as soon as something starts playing, so an unattended
    fetch never competes with a stream for bandwidth.
    """
    if not os.path.isdir(UPDATE_DIR):
        try:
            os.makedirs(UPDATE_DIR)
        except OSError as exc:
            log("Cannot create {0}: {1}".format(UPDATE_DIR, exc), xbmc.LOGERROR)
            return False

    expected_sha = None
    if setting_bool("verify_checksum"):
        expected_sha = resolve_checksum(release)
        if not expected_sha:
            # Fail closed: "verify" on with nothing to verify against is not a pass.
            log("No checksum published for {0}; not staging it".format(release["tar_name"]), xbmc.LOGERROR)
            return False

    # Leftovers from a download interrupted by a reboot or crash.
    for existing in os.listdir(UPDATE_DIR):
        if existing.endswith(".tar.part"):
            _cleanup(os.path.join(UPDATE_DIR, existing))

    dest_path = os.path.join(UPDATE_DIR, release["tar_name"])
    tmp_path = dest_path + ".part"

    hasher = hashlib.sha256()
    total = release.get("tar_size") or 0
    written = 0

    try:
        with urllib.request.urlopen(_http_request(release["tar_url"]), timeout=30) as resp, open(tmp_path, "wb") as out:
            chunk_size = 1024 * 1024
            while True:
                if stop_on_playback and is_playing():
                    raise DownloadAborted()
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
            out.flush()
            os.fsync(out.fileno())
    except DownloadAborted:
        log("Playback started; download of {0} abandoned".format(release["tar_name"]))
        _cleanup(tmp_path)
        raise
    except (urllib.error.URLError, OSError) as exc:
        log("Download failed: {0}".format(exc), xbmc.LOGERROR)
        _cleanup(tmp_path)
        return False

    if total and written != total:
        log("Short download: expected {0} bytes, got {1}".format(total, written), xbmc.LOGERROR)
        _cleanup(tmp_path)
        return False

    if expected_sha:
        digest = hasher.hexdigest().lower()
        if digest != expected_sha:
            log(
                "Checksum mismatch: expected {0}, got {1}".format(expected_sha, digest),
                xbmc.LOGERROR,
            )
            _cleanup(tmp_path)
            return False

    # Only now replace whatever was staged before, so only one is ever pending.
    for existing in os.listdir(UPDATE_DIR):
        if existing.endswith(".tar") and existing != release["tar_name"]:
            _cleanup(os.path.join(UPDATE_DIR, existing))

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


def reboot_when_idle():
    """Reboot, but never over playback: wait for it to stop first."""
    monitor = xbmc.Monitor()
    while is_playing():
        if monitor.waitForAbort(30):
            return
    notify(_(30029))
    if monitor.waitForAbort(3):
        return
    xbmc.executebuiltin("Reboot")


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
        is_samurihl, installed_ts, distro_arch = get_installed_build()
        try:
            releases = fetch_releases_list(limit=20, distro_arch=distro_arch)
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
        has_checksum = r["sha256"] or r["sha256_url"]
        checksum_flag = "" if has_checksum else "  [{0}]".format(_(30043))
        labels.append("{0}  ({1}){2}{3}".format(r["tag"], size, checksum_flag, marker))

    dialog = xbmcgui.Dialog()
    index = dialog.select(_(30040), labels)
    if index < 0:
        return

    chosen = releases[index]

    # Switching a non-samurihl build over is allowed, but only knowingly.
    prompt = _(30044).format(chosen["tag"])
    if not is_samurihl:
        prompt = _(30050) + "[CR]" + prompt
    if not dialog.yesno(
        _(30020),
        prompt,
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
    Returns False when an unattended cycle was put off because something was
    playing (the service retries sooner), True otherwise.
    """
    if not manual and not setting_bool("enabled"):
        return True

    is_samurihl, installed_ts, distro_arch = get_installed_build()
    if not is_samurihl:
        # Never offer a samurihl tar to official CoreELEC or another fork;
        # "Browse releases..." remains the deliberate way to switch.
        log("Installed build is not a {0} build; not checking".format(BUILDER_NAME), xbmc.LOGWARNING)
        if manual:
            notify(_(30051), xbmcgui.NOTIFICATION_WARNING)
        return True

    if not manual and is_playing():
        log("Playback active; deferring update check")
        return False

    progress = xbmcgui.DialogProgressBG() if manual else None
    if progress:
        progress.create(_(30020), _(30021))

    try:
        try:
            release = fetch_latest_release(distro_arch)
        except (urllib.error.URLError, ValueError) as exc:
            log("Update check failed: {0}".format(exc), xbmc.LOGERROR)
            if manual:
                notify(_(30024), xbmcgui.NOTIFICATION_ERROR)
            return True

        if release is None:
            log("No suitable release with a .tar asset was found", xbmc.LOGWARNING)
            if manual:
                notify(_(30030), xbmcgui.NOTIFICATION_WARNING)
            return True

        state = load_state()

        is_newer = installed_ts is None or release["timestamp"] > installed_ts

        if not is_newer:
            log("Up to date: installed={0} latest={1}".format(installed_ts, release["timestamp"]))
            if manual:
                notify(_(30023).format(release["tag"]))
            return True

        already_downloaded = state.get("downloaded_timestamp") == release["timestamp"]
        already_notified = state.get("notified_timestamp") == release["timestamp"]

        if setting_bool("auto_download") and not already_downloaded:
            if progress:
                progress.update(0, message=_(30025).format(release["tar_name"]))
            try:
                ok = download_and_verify(release, progress_dialog=progress, stop_on_playback=not manual)
            except DownloadAborted:
                return False
            if not ok:
                notify(_(30031), xbmcgui.NOTIFICATION_ERROR)
                return True

            state["downloaded_timestamp"] = release["timestamp"]
            save_state(state)

            if setting_bool("auto_reboot"):
                reboot_when_idle()
            elif is_playing():
                # No modal prompt over a film; the notification is enough.
                notify(_(30029))
            elif xbmcgui.Dialog().yesno(
                _(30020),
                _(30028),
                yeslabel=_(30033),
                nolabel=_(30034),
            ):
                xbmc.executebuiltin("Reboot")
            return True

        if already_downloaded:
            if manual:
                notify(_(30029))
            return True

        # Notify-only path
        if manual or not (setting_bool("notify_only_once_per_build") and already_notified):
            notify(_(30022).format(release["tag"]))
            state["notified_timestamp"] = release["timestamp"]
            save_state(state)

        return True

    finally:
        if progress:
            progress.close()
