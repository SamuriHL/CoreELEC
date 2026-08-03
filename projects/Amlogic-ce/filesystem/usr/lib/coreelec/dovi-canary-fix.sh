#!/bin/sh
# dovi-canary-fix - correct dovi.ko's stack-canary offset BEFORE CoreELEC's
# dovi-loader insmods it.
#
# Amlogic's dovi.ko is built against an Android GKI kernel and hardcodes
# offsetof(task_struct, stack_canary). On CoreELEC that offset differs, so the
# module compares an unrelated task_struct field as its "canary"; when that
# field legitimately moves, the check spuriously fails, __stack_chk_fail only
# warns and returns, and the module then executes a trap -> fatal in the vsync
# ISR -> the box reboots during Dolby Vision playback.
#
# This corrects the offset IN RAM. Nothing persistent is modified: the fixed
# copy lives in tmpfs and is bind-mounted over the path the loader reads, so a
# reboot - or dropping a different build in the update folder - leaves no trace
# and no patched binary behind.
#
# Fails safe at every step: on any problem the stock module is left untouched
# and the loader proceeds exactly as it does today.
set -u

PATCHER=/usr/lib/coreelec/patch_dovi_canary.py
TMP=/run/dovi.ko

log() { logger -t dovi-canary-fix "$*" 2>/dev/null; echo "dovi-canary-fix: $*"; }

rm -f "$TMP"

[ -x /usr/bin/python3 ] || { log "python3 unavailable - leaving module untouched"; exit 0; }
[ -f "$PATCHER" ]       || { log "patcher not found at $PATCHER - leaving module untouched"; exit 0; }

# same search order as /usr/lib/coreelec/dovi-loader
SRC=""
for c in /storage/.config/dovi.ko /flash/dovi.ko /storage/dovi.ko; do
    if [ -f "$c" ]; then SRC="$c"; break; fi
done
[ -n "$SRC" ] || { log "no local dovi.ko (loader will use the Android partition) - nothing to do"; exit 0; }

OUT=$(python3 "$PATCHER" --in "$SRC" --out "$TMP" 2>&1); RC=$?
echo "$OUT" | while IFS= read -r line; do [ -n "$line" ] && log "$line"; done

if [ "$RC" -ne 0 ]; then
    log "patcher declined (rc=$RC) - loader will use $SRC unchanged"
    rm -f "$TMP"; exit 0
fi
if [ ! -s "$TMP" ]; then
    # patcher exits 0 without writing when the module is already correct
    log "module already correct - loader will use $SRC unchanged"
    exit 0
fi
if mount --bind "$TMP" "$SRC"; then
    log "corrected module bind-mounted over $SRC (RAM only, not persisted)"
else
    log "bind mount over $SRC failed - loader will use it unchanged"
    rm -f "$TMP"
fi
exit 0
