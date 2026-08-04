#!/bin/sh
# dovi-canary-cleanup - drop the bind mount left by dovi-canary-fix once
# CoreELEC's dovi-loader has insmod'd the module.
#
# The mount is only needed for the instant between our service and the loader.
# Leaving it up for the whole session shadows the real dovi.ko from every tool
# that looks at that path, which is worse than cosmetic:
#
#   * `ls` / `sha256sum` report the RAM copy, so a user checking their module
#     sees a date and hash that do not match what they downloaded;
#   * busybox `cp -f` and `rm` fail outright on a mountpoint, so build-switch
#     and dovi-switch silently fail to stage a different build's module;
#   * an O_TRUNC write - which is what SMB, NFS and most file managers do -
#     SUCCEEDS into the tmpfs copy and is then lost at the next reboot, so
#     replacing dovi.ko over a network share appears to work and silently
#     reverts.
#
# The on-disk file was never modified in any of those cases, but the reports
# are misleading. Unmounting here collapses the exposure to a few seconds of
# early boot, during which nothing else touches the file.
#
# Caveat: after this runs, a manual `systemctl restart opentee_linuxdriver`
# would re-insmod the STOCK module (unpatched). Reboot instead.
set -u

MARK=/run/dovi-canary-fix.mnt
TMP=/run/dovi.ko

log() { logger -t dovi-canary-cleanup "$*" 2>/dev/null; echo "dovi-canary-cleanup: $*"; }

SRC=""
[ -f "$MARK" ] && SRC=$(cat "$MARK" 2>/dev/null)

# Marker missing (older fix script, or /run cleared): fall back to the loader's
# search order and take whichever path is currently a tmpfs mountpoint.
if [ -z "$SRC" ]; then
    for c in /storage/.config/dovi.ko /flash/dovi.ko /storage/dovi.ko; do
        if grep -q " ${c} tmpfs " /proc/mounts 2>/dev/null; then SRC="$c"; break; fi
    done
fi

if [ -z "$SRC" ]; then
    rm -f "$TMP" "$MARK"
    exit 0
fi

if umount "$SRC" 2>/dev/null; then
    log "removed the boot-time bind mount over $SRC (module already loaded)"
    rm -f "$TMP"
else
    # Leave $TMP alone - it is still the source of a live mount.
    log "could not unmount $SRC - it stays shadowed until reboot"
fi

rm -f "$MARK"
exit 0
