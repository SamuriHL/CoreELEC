#!/usr/bin/env python3
"""Pre-flight for the fork's patch stacks.

Catches the failure mode that cost a build on 2026-08-08: a hunk header whose
declared line counts disagree with the hunk body. GNU patch reads exactly the
number of lines the header claims, silently ignores the rest of the body, and
STILL EXITS 0 - so the patch "applies", the build succeeds, and the change is
simply absent from the binary. A malformed hunk also desynchronises patch for
every later hunk in the same file.

Two independent checks:
  1. header arithmetic - every "@@ -a,b +c,d @@" must match its body
  2. apply-and-assert  - optionally apply the stack to a pristine tarball and
     assert that caller-supplied marker strings are actually present afterwards

Check 2 is the one that matters: "patch returned 0" is not evidence that the
code arrived. Only reading the patched source is.

Usage:
  check-patches.py headers <patch>...
  check-patches.py apply --tarball T [--strip N]
                         --assertions <file> | --marker 'file:string:count'
                         <patch>...

Typical invocation for the common_drivers stack, from the CoreELEC root:

  P=projects/Amlogic-ce/packages/linux-drivers/amlogic/common_drivers/patches
  projects/Amlogic-ce/tools/check-patches.py apply \\
      --tarball sources/common_drivers/common_drivers-<sha>.tar.gz \\
      --assertions $P/ASSERTIONS $(ls -1 $P/*.patch | sort)
"""

import argparse
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HUNK_RE = re.compile(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@')
FILE_HDR = ('--- ', '+++ ', 'diff ')


def hunks(lines):
    """Yield (index, declared_old, declared_new, body) for each hunk."""
    i = 0
    while i < len(lines):
        m = HUNK_RE.match(lines[i])
        if not m:
            i += 1
            continue
        j = i + 1
        body = []
        while j < len(lines):
            line = lines[j]
            if line.startswith('@@') or line.startswith(FILE_HDR):
                break
            if not (line.startswith(('-', '+', ' ')) or line == ''):
                break
            body.append(line)
            j += 1
        # trailing blank lines separate the hunk from what follows; they are
        # not part of it
        while body and body[-1] == '':
            body.pop()
        yield i, int(m.group(2)), int(m.group(4)), body
        i = j


def check_headers(paths):
    bad = 0
    for p in paths:
        lines = Path(p).read_text().split('\n')
        for idx, want_old, want_new, body in hunks(lines):
            # a bare empty line inside a body is a context line whose trailing
            # space was stripped somewhere in transit
            got_old = sum(1 for l in body if l.startswith(('-', ' ')) or l == '')
            got_new = sum(1 for l in body if l.startswith(('+', ' ')) or l == '')
            if (got_old, got_new) != (want_old, want_new):
                print(f"MISMATCH {Path(p).name} hunk at line {idx + 1}: "
                      f"header says -{want_old},+{want_new} but body has "
                      f"-{got_old},+{got_new}")
                bad = 1
    print("patch headers: OK" if not bad
          else "patch headers: BROKEN - patch would silently truncate these")
    return bad


def check_apply(tarball, strip, patches, markers):
    tmp = Path(tempfile.mkdtemp(prefix='patchcheck.'))
    try:
        with tarfile.open(tarball) as tf:
            tf.extractall(tmp)
        roots = [d for d in tmp.iterdir() if d.is_dir()]
        if len(roots) != 1:
            print(f"expected one top-level dir in {tarball}, found {len(roots)}")
            return 1
        root = roots[0]

        for p in patches:
            with open(p) as fh:
                r = subprocess.run(['patch', f'-p{strip}'], cwd=root, stdin=fh,
                                   capture_output=True, text=True)
            if r.returncode != 0:
                print(f"APPLY FAILED {Path(p).name} (rc={r.returncode})")
                for line in (r.stdout + r.stderr).splitlines():
                    if 'FAILED' in line or 'malformed' in line:
                        print("   " + line)
                return 1

        rejects = list(root.rglob('*.rej'))
        if rejects:
            print(f"REJECTS: {len(rejects)} .rej file(s) left behind")
            return 1

        # the check that actually proves the code arrived
        bad = 0
        for spec in markers:
            # the needle may itself contain colons, so bind the path to the
            # first separator and the count to the last
            relpath, rest = spec.split(':', 1)
            needle, want = rest.rsplit(':', 1)
            text = (root / relpath).read_text(errors='replace')
            got = text.count(needle)
            ok = got == int(want)
            print(f"  {'ok  ' if ok else 'FAIL'} {relpath}: "
                  f"{needle!r} x{got} (expected {want})")
            if not ok:
                bad = 1
        print("patch content: OK" if not bad
              else "patch content: WRONG - patch exited 0 but the code is not there")
        return bad
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)

    h = sub.add_parser('headers')
    h.add_argument('patches', nargs='+')

    a = sub.add_parser('apply')
    a.add_argument('--tarball', required=True)
    a.add_argument('--strip', type=int, default=1)
    a.add_argument('--marker', action='append', default=[],
                   metavar='FILE:STRING:COUNT')
    a.add_argument('--assertions', metavar='FILE',
                   help='file of FILE:STRING:COUNT lines (# comments allowed); '
                        'normally the ASSERTIONS file beside the patches')
    a.add_argument('patches', nargs='+')

    args = ap.parse_args()
    if args.cmd == 'headers':
        return check_headers(args.patches)

    markers = list(args.marker)
    if args.assertions:
        for line in Path(args.assertions).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                markers.append(line)
    if not markers:
        print("refusing to run with no assertions: 'patch returned 0' is not "
              "evidence that the code arrived")
        return 1

    return max(check_headers(args.patches),
               check_apply(args.tarball, args.strip, args.patches, markers))


if __name__ == '__main__':
    sys.exit(main())
