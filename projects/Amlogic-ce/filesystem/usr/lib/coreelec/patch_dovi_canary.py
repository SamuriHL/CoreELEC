#!/usr/bin/env python3
"""
patch_dovi_canary.py - fix spurious "stack-protector" kernel panics caused by
Amlogic's dovi.ko reading the wrong task_struct offset for its stack canary.

THE BUG
  dovi.ko is built against an Android GKI kernel and hardcodes
  offsetof(struct task_struct, stack_canary) at build time.  On CoreELEC that
  offset is different, so every stack-protector-instrumented function in the
  module stores/compares some UNRELATED task_struct field as its "canary".
  That field is a process-group hash-list pointer, which legitimately moves
  whenever a nearby process exits - so the check spuriously "fails".  Amlogic's
  __stack_chk_fail only pr_warn()s and RETURNS, so execution falls through into
  a compiler trap block (brk #0x5512) whose immediate is unregistered on 5.15:
  "Unexpected kernel BRK exception at EL1" -> fatal in the vsync ISR -> reboot.

  Symptom: random reboots during Dolby Vision playback, and in dmesg/pstore:
      stack-protector: Kernel stack is corrupted in: <fn> [dovi_gen_...]
      Kernel panic - not syncing: BRK handler: Fatal exception in interrupt

THE FIX
  Rewrite the imm12 field of every canary load so it points at the offset THIS
  kernel actually uses.  Nothing else changes: same size, same symbols, same
  vermagic, no signature to invalidate.  Idempotent.

USAGE (as root, ON the box)
      python3 patch_dovi_canary.py              # detect, patch, back up, install
      python3 patch_dovi_canary.py --dry-run    # report only, change nothing
      python3 patch_dovi_canary.py --in a.ko --out b.ko    # offline, no install
  Then reboot.  Check with:  dmesg | grep -c stack-protector   (want 0)
  Roll back:  rm /storage/.config/dovi.ko && reboot

HOW THE OFFSET IS FOUND (no source, BTF or debug info needed)
  task_struct always lays out:
      stack_canary / real_parent+8 / parent+16 / children+24 / sibling+40 /
      group_leader+56
  In init_task (address from /proc/kallsyms, memory via /proc/kcore),
  real_parent == parent == group_leader == &init_task, and sibling is an empty
  list_head so both its pointers equal &init_task+off(sibling).  That 5-pointer
  signature pins the block; stack_canary is the word before it, and is checked
  to be non-zero with a zero low byte (get_random_canary() applies CANARY_MASK).
  Scanning kernel .text for the canary idiom does NOT work - CoreELEC's kernel
  is not itself stack-protector instrumented (__stack_chk_fail has zero callers
  in vmlinux; it is exported solely for out-of-tree modules).
"""
import argparse, os, shutil, struct, sys

# Cross-check table: kernel build-id -> known-good offset. Detection is primary;
# these are verified against that kernel's asm-offsets.h AND its vmlinux DWARF.
KNOWN_KERNELS = {
    '923659ef12bac1513b1117247c32b85ed803a12f': 0x5c0,   # CE22 samurihl 5.15.196
}

SEARCH = ['/storage/.config/dovi.ko', '/flash/dovi.ko', '/storage/dovi.ko']
INSTALL = '/storage/.config/dovi.ko'

MRS_SP_EL0 = 0xD5384100          # mrs xN, SP_EL0        (mask 0xFFFFFFE0)
LDR_UIMM   = 0xF9400000          # ldr xT,[xN,#imm12*8]  (mask 0xFFC00000)


# ---------------------------------------------------------------- kernel probe
class Kcore:
    def __init__(self):
        self.f = open('/proc/kcore', 'rb')
        h = self.f.read(64)
        phoff, = struct.unpack_from('<Q', h, 0x20)
        phentsz, = struct.unpack_from('<H', h, 0x36)
        phnum, = struct.unpack_from('<H', h, 0x38)
        self.segs = []
        for i in range(phnum):
            self.f.seek(phoff + i * phentsz)
            ph = self.f.read(phentsz)
            if struct.unpack_from('<I', ph, 0)[0] != 1:      # PT_LOAD
                continue
            self.segs.append((struct.unpack_from('<Q', ph, 0x10)[0],
                              struct.unpack_from('<Q', ph, 0x08)[0],
                              struct.unpack_from('<Q', ph, 0x20)[0]))

    def read(self, va, n):
        for vaddr, off, fsz in self.segs:
            if vaddr <= va and va + n <= vaddr + fsz:
                self.f.seek(off + (va - vaddr))
                return self.f.read(n)
        return None


def kernel_build_id():
    try:
        notes = open('/sys/kernel/notes', 'rb').read()
    except OSError:
        return None
    i = 0
    while i + 12 <= len(notes):
        nsz, dsz, typ = struct.unpack_from('<III', notes, i)
        if nsz == 0 and dsz == 0:
            break
        name = notes[i + 12:i + 12 + nsz].rstrip(b'\0')
        doff = i + 12 + ((nsz + 3) & ~3)
        if name == b'GNU' and typ == 3:
            return notes[doff:doff + dsz].hex()
        i = doff + ((dsz + 3) & ~3)
    return None


def detect_canary_offset(verbose=True):
    """Return offsetof(task_struct, stack_canary), or None with a reason."""
    init_task = None
    try:
        for line in open('/proc/kallsyms'):
            p = line.split()
            if len(p) >= 3 and p[2] == 'init_task':
                init_task = int(p[0], 16)
                break
    except OSError as e:
        return None, 'cannot read /proc/kallsyms (%s)' % e
    if not init_task:
        return None, 'init_task not found in /proc/kallsyms'
    if init_task == 0:
        return None, 'kallsyms addresses are zeroed (kptr_restrict) - need root'
    try:
        kc = Kcore()
    except OSError as e:
        return None, 'cannot read /proc/kcore (%s)' % e
    buf = kc.read(init_task, 8192)
    if buf is None:
        return None, 'init_task %#x not mapped in /proc/kcore' % init_task

    u = struct.unpack('<1024Q', buf)
    hits = []
    for i in range(1, len(u) - 8):
        if u[i] != init_task or u[i + 1] != init_task or u[i + 6] != init_task:
            continue                                   # real_parent/parent/group_leader
        sib = init_task + i * 8 + 32                   # sibling: empty list_head -> self
        if u[i + 4] != sib or u[i + 5] != sib:
            continue
        canary = u[i - 1]
        if canary == 0 or (canary & 0xFF) != 0:        # get_random_canary(): low byte 0
            continue
        hits.append((i - 1) * 8)
    if not hits:
        return None, 'task_struct signature not found in init_task'
    if len(hits) > 1:
        return None, 'ambiguous (%s)' % [hex(h) for h in hits]
    if verbose:
        print('detected from init_task @ %#x: stack_canary at %#x (%d)'
              % (init_task, hits[0], hits[0]))
    return hits[0], None


# ------------------------------------------------------------------ ELF / patch
def exec_sections(blob):
    shoff, = struct.unpack_from('<Q', blob, 0x28)
    shentsz, = struct.unpack_from('<H', blob, 0x3a)
    shnum, = struct.unpack_from('<H', blob, 0x3c)
    shstrndx, = struct.unpack_from('<H', blob, 0x3e)
    stroff, = struct.unpack_from('<Q', blob, shoff + shstrndx * shentsz + 0x18)
    for i in range(shnum):
        b = shoff + i * shentsz
        nameoff, sh_type = struct.unpack_from('<II', blob, b)
        flags, = struct.unpack_from('<Q', blob, b + 0x08)
        off, size = struct.unpack_from('<QQ', blob, b + 0x18)
        if sh_type == 8 or not (flags & 0x4):
            continue
        end = blob.index(b'\0', stroff + nameoff)
        yield blob[stroff + nameoff:end].decode(), off, size


def find_sites(blob):
    sites = []
    for _, off, size in exec_sections(bytes(blob)):
        n = size // 4
        if n == 0:
            continue
        words = struct.unpack_from('<%dI' % n, blob, off)
        for i, w in enumerate(words):
            if (w & 0xFFFFFFE0) != MRS_SP_EL0:
                continue
            rt = w & 0x1F
            for j in range(i + 1, min(i + 9, n)):
                v = words[j]
                if (v & 0xFFC00000) != LDR_UIMM or ((v >> 5) & 0x1F) != rt:
                    continue
                sites.append((off + j * 4, v, ((v >> 10) & 0xFFF) * 8))
                break
    return sites


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='src')
    ap.add_argument('--out', dest='dst')
    ap.add_argument('--target-offset', type=lambda s: int(s, 0),
                    help='override: offsetof(task_struct,stack_canary)')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    # ---- target offset: detect, then cross-check against the known table ----
    target, why = a.target_offset, None
    if target is not None:
        print('stack_canary offset %#x (supplied)' % target)
    else:
        target, why = detect_canary_offset()
        bid = kernel_build_id()
        known = KNOWN_KERNELS.get(bid)
        if target is None:
            if known is not None:
                target = known
                print('detection failed (%s); using known value for this kernel '
                      '(%s): %#x' % (why, bid[:12], target))
            else:
                sys.exit('REFUSING: could not determine the canary offset (%s),\n'
                         'and kernel %s is not in the known table.\n'
                         'Run as root, or pass --target-offset 0x<offset> taken\n'
                         "from TSK_STACK_CANARY in that kernel's asm-offsets.h."
                         % (why, bid))
        elif known is not None and known != target:
            sys.exit('REFUSING: detected %#x but kernel %s is recorded as %#x.\n'
                     'Something is wrong - not guessing.' % (target, bid[:12], known))
    if target % 8 or not 0 < target <= 4095 * 8:
        sys.exit('REFUSING: %#x is not a valid 8-aligned LDR offset' % target)

    # ---- input ------------------------------------------------------------
    src = a.src or next((p for p in SEARCH if os.path.isfile(p)), None)
    if not src:
        sys.exit('REFUSING: no dovi.ko in %s.\nIf yours loads from the Android '
                 'partition, copy it out and pass --in.' % ', '.join(SEARCH))
    blob = bytearray(open(src, 'rb').read())
    if blob[:4] != b'\x7fELF':
        sys.exit('REFUSING: %s is not an ELF file' % src)
    print('input: %s (%d bytes)' % (src, len(blob)))

    sites = find_sites(blob)
    if not sites:
        sys.exit('REFUSING: no canary loads found - this module is not '
                 'stack-protector instrumented, so it cannot have this bug.')
    tally = {}
    for _, _, off in sites:
        tally[off] = tally.get(off, 0) + 1
    for off, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print('  %d sites currently read task_struct+%#x' % (n, off))

    if list(tally) == [target]:
        print('\nAlready correct - nothing to do.')
        return
    cur = max(tally, key=lambda k: tally[k])
    if tally[cur] != len(sites):
        sys.exit('REFUSING: mixed offsets %s - module not shaped as expected.' % tally)

    # ---- patch ------------------------------------------------------------
    newimm = target // 8
    for fo, v, _ in sites:
        struct.pack_into('<I', blob, fo, (v & ~(0xFFF << 10)) | (newimm << 10))
    print('\nrewrote %d canary loads: task_struct+%#x -> +%#x'
          % (len(sites), cur, target))
    if a.dry_run:
        print('--dry-run: nothing written.')
        return

    dst = a.dst or INSTALL
    if dst == INSTALL:
        keep = INSTALL + '.bak' if os.path.isfile(INSTALL) else \
               '/storage/.config/dovi.ko.ORIGINAL'
        os.makedirs('/storage/.config', exist_ok=True)
        shutil.copy2(src if keep.endswith('ORIGINAL') else INSTALL, keep)
        print('backed up -> %s' % keep)
    os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
    with open(dst, 'wb') as f:
        f.write(blob)
        f.flush()
        os.fsync(f.fileno())
    print('wrote %s' % dst)
    if dst == INSTALL:
        print('\nReboot to load it. Afterwards:\n'
              '  dmesg | grep -c stack-protector   # want 0\n'
              '  ls /sys/fs/pstore/                # want no dmesg-ramoops-*\n'
              'Roll back: rm %s && reboot' % INSTALL)


if __name__ == '__main__':
    main()
