#!/usr/bin/env python3
"""Run the Phase 1 acceptance checks and print a pass/fail table.

    test_phase1.py <liborender.so> <libpcm_bridge.so>

Every check drives the real helper, the real engine and the real PCM bridge
with bytes this script makes itself: an OPCM stream header and a synthesised
tone. Nothing here needs a soundtrack, which is why nothing here is skipped -
the encoded test streams this used to want are commercial audio that cannot
live in the tree, so the checks that needed them could never be run by anyone
who had not been handed the files privately.

The PCM bridge rather than the object bridge for the same reason: it accepts
audio a test can generate, so what is exercised end to end is the helper's
framing, the engine's construction at a named rate, and the reset boundary the
host relies on - the parts that are not codec-specific and were never what the
soundtracks were proving.

    OMNI_HELPER   the helper binary to run. Not in the tree - it is built by
                  package.mk, or by hand:
                      cc -O2 -I<orender_ffi/include> \\
                         -o omniphony-helper ../sources/omniphony-helper.c -ldl
                  Defaults to ./omniphony-helper.
    OMNI_CONFIG   the engine's config. Defaults to direct.yaml beside this.
    OMNI_RATE     the rate to open the renderer at. Defaults to 48000. The
                  engine builds its head model at this rate, and every rate but
                  48000 resamples it first, so a non-default value here is also
                  a check that the helper survives the slow open.
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drive import (Helper, opcm_header, opcm_tone, open_payload, ST, LABEL_L, LABEL_R,
                   OP_OPEN, OP_CLOSE, OP_FEED, OP_RESET,
                   ST_OK, ST_PROTOCOL, ST_STATE, ST_BRIDGE, ST_INFO)

HERE = os.path.dirname(os.path.abspath(__file__))

args = [a for a in sys.argv[1:] if not a.startswith("-")]
if len(args) < 2 or any(a in ("-h", "--help") for a in sys.argv[1:]):
    print(__doc__.strip())
    sys.exit(0 if len(sys.argv) > 1 else 2)

LIB, BRIDGE = args[0], args[1]
EXE = os.environ.get("OMNI_HELPER", "./omniphony-helper")
CONFIG = os.environ.get("OMNI_CONFIG", os.path.join(HERE, "direct.yaml"))
RATE = int(os.environ.get("OMNI_RATE", "48000"))

for label, path in (("engine", LIB), ("bridge", BRIDGE), ("helper", EXE), ("config", CONFIG)):
    if not os.path.exists(path):
        sys.exit(f"no {label} at {path} - see --help")

CHANNELS = [LABEL_L, LABEL_R]
# Twelve seconds of patience for the open, in 20 ms looks. The engine's head
# model is resampled for any rate but 48000, which is seconds on slow hardware.
OPEN_POLL_S, OPEN_POLLS = 0.02, 600
BLOCK = 4096  # frames per FEED, comfortably more than one render block

results = []


def check(ok, what, detail=""):
    results.append((what, ok))
    print(f"  {what:<52} {'PASS' if ok else 'FAIL'}{('  ' + detail) if detail else ''}")


def env():
    e = dict(os.environ)
    e["LD_LIBRARY_PATH"] = os.path.dirname(LIB)
    return e


def opened(rate=RATE):
    """A helper with the engine up and the bridge waiting for a header."""
    h = Helper(EXE, env())
    h.send(OP_OPEN, open_payload(LIB, CONFIG, BRIDGE, rate=rate))
    # The engine is built inside this call, and off 48 kHz that means resampling
    # the head model first - seconds on slow hardware. Wait for it to answer
    # rather than assuming it already has: draining is non-blocking, so a loop
    # without the sleep spins past the whole open and finds nothing. This is the
    # same wait the host does, for the same reason.
    for _ in range(OPEN_POLLS):
        h.drain()
        if any(t.startswith("open ") for _, t in h.status):
            break
        time.sleep(OPEN_POLL_S)
    return h


def feed_pcm(h, frames, start=0, rate=RATE):
    h.send(OP_FEED, opcm_tone(frames, len(CHANNELS), rate, start=start))
    h.drain()


# ---- 1. malformed input is refused, with the right answer ------------------
print("=" * 74)
print(" 1. malformed input is refused, and says which way it was wrong")
print("=" * 74)

# Each case names the exit code and the status code the helper owes, so a build
# that swallows bad input, or reports the wrong kind of wrong, fails here
# instead of passing on "it did not crash".
cases = [
    ("truncated command header", 5, ST_PROTOCOL,
     lambda h: h.send_raw(b"OMNC\x02\x00\x00\x00")),
    ("payload shorter than its length", 5, ST_PROTOCOL,
     lambda h: h.send_raw(b"OMNC" + struct.pack("<BBHII", OP_FEED, 0, 0, 4096, 0) + b"short")),
    ("garbage instead of a command", 5, ST_PROTOCOL,
     lambda h: h.send_raw(b"\xde\xad\xbe\xef" * 8)),
    ("payload length of 4 GiB", 5, ST_PROTOCOL,
     lambda h: h.send_raw(b"OMNC" + struct.pack("<BBHII", OP_FEED, 0, 0, 0xFFFFFFF0, 0))),
    ("FEED before OPEN", 5, ST_STATE,
     lambda h: h.send(OP_FEED, b"\x00" * 64)),
    ("OPEN without a lib", 5, None,
     lambda h: h.send(OP_OPEN, b"config=/dev/null\n")),
]

for label, want_rc, want_st, act in cases:
    h = Helper(EXE, env())
    act(h)
    rc, err = h.finish()
    codes = [c for c, _ in h.status]
    ok = rc == want_rc and (want_st is None or want_st in codes)
    names = ",".join(ST.get(c, str(c)) for c in codes) or "-"
    check(ok, label, f"rc={rc} (want {want_rc})  status={names}")

# Bytes that are not an OPCM stream at all: the bridge cannot read one packet of
# it and cannot read any of them, which is the case the helper is meant to tell
# apart from a damaged file. It reports and exits rather than pushing silence.
h = opened()
rnd = os.urandom(4096)
for _ in range(64):
    if not h.send(OP_FEED, rnd):
        break
    h.drain()
h.send(OP_CLOSE)
rc, err = h.finish()
codes = [c for c, _ in h.status]
check(rc == 7 and ST_BRIDGE in codes, "random bytes are reported, not swallowed",
      f"rc={rc} (want 7)  status={','.join(ST.get(c, str(c)) for c in codes)}")

# ---- 2. synthetic PCM renders ----------------------------------------------
print()
print("=" * 74)
print(f" 2. a stream this script generated renders, at {RATE} Hz")
print("=" * 74)

h = opened()
open_lines = [t for c, t in h.status if c == ST_OK and t.startswith("open ")]
check(bool(open_lines), "the engine reports itself open",
      open_lines[0] if open_lines else "no open status")
check(any(f"rate={RATE}" in t for t in open_lines),
      "and open at the rate it was asked for")

h.send(OP_FEED, opcm_header(CHANNELS, RATE))
h.drain()
for i in range(8):
    feed_pcm(h, BLOCK, start=i * BLOCK)
h.send(OP_CLOSE)
rc, err = h.finish()

frames = sum(f for f, _ in h.audio)
pts = [p for _, p in h.audio]
check(rc == 0, "the helper closes cleanly", f"rc={rc}")
check(frames > 0, "audio comes back", f"{frames} frames in {len(h.audio)} blocks")
check(all(b >= a for a, b in zip(pts, pts[1:])), "its timestamps never go backwards")
# Two channels out, whatever went in. Nothing on the wire says so - an audio
# frame carries a frame count and the reader sizes the block as frames x 2 x
# f32 - so what proves it is that every byte the helper wrote was accounted for
# under that assumption. A different channel count would have left the reader
# mid-block, and the next header it looked for would have been sample data.
check(h.buf == b"", "every block was stereo, so nothing was left unparsed",
      f"{len(h.buf)} bytes unaccounted for")

# ---- 3. the reset boundary -------------------------------------------------
print()
print("=" * 74)
print(" 3. RESET draws a boundary the host can trust")
print("=" * 74)

h = opened()
h.send(OP_FEED, opcm_header(CHANNELS, RATE))
h.drain()
for i in range(4):
    feed_pcm(h, BLOCK, start=i * BLOCK)

h.send(OP_RESET)
h.drain()
# A reset returns the bridge to expecting a header, so the new timeline starts
# with one - the same thing the host does after a seek.
h.send(OP_FEED, opcm_header(CHANNELS, RATE))
h.drain()
for i in range(4):
    feed_pcm(h, BLOCK, start=i * BLOCK)

h.send(OP_RESET)
h.drain()
h.send(OP_CLOSE)
rc, err = h.finish()

marks = [(i, t) for i, e in enumerate(h.events) if e[0] == "status"
         for t in [e[2]] if t.startswith("reset epoch=")]
check(len(marks) == 2, "one acknowledgement per reset, and only one",
      f"{len(marks)} marks: {[t for _, t in marks]}")
check([t for _, t in marks] == ["reset epoch=1", "reset epoch=2"],
      "the epochs count up, so none can be missed")

if marks:
    at = marks[0][0]
    before = [e[2] for e in h.events[:at] if e[0] == "audio"]
    after = [e[2] for e in h.events[at:] if e[0] == "audio"]
    check(bool(before) and bool(after), "audio lands on both sides of the mark",
          f"{len(before)} before, {len(after)} after")
    # This is the property the host's stale-audio drop rests on. Each timeline
    # has to be sane on its own, and the two have to be distinguishable: the
    # engine restarts its sample count at a reset, so the new timeline begins
    # behind where the old one ended. That step backwards is the thing a host
    # cannot infer safely - two seeks in quick succession, or a seek taken when
    # the only block rendered was the first, leave nothing to step back from -
    # which is why the mark exists and why the host counts marks rather than
    # comparing timestamps.
    mono_b = all(a <= b for a, b in zip(before, before[1:]))
    mono_a = all(a <= b for a, b in zip(after, after[1:]))
    check(mono_b and mono_a, "each timeline's timestamps rise on their own",
          f"old {before[0]}..{before[-1]}, new {after[0]}..{after[-1]}")
    check(after[0] < before[-1], "and the new one starts behind the old one's end",
          f"{after[0]} < {before[-1]}")
else:
    check(False, "audio lands on both sides of the mark", "no reset mark to split on")
    check(False, "each timeline's timestamps rise on their own")
    check(False, "and the new one starts behind the old one's end")

check(rc == 0, "the helper survives two resets and closes cleanly", f"rc={rc}")

# ---- 4. the decoded rate is reported, even when it is not the one asked for --
print()
print("=" * 74)
print(" 4. the stream line says what the bridge actually decoded at")
print("=" * 74)


def stream_lines(h):
    return [t for c, t in h.status if c == ST_INFO and t.startswith("stream ")]


def reported_rate(h):
    """The rate= field of the last stream line, or None if there is none."""
    lines = stream_lines(h)
    if not lines:
        return None
    at = lines[-1].find("rate=")
    return int(lines[-1][at + 5:].split()[0]) if at >= 0 else None


def run_at(open_rate, header_rate):
    """Open the engine at one rate, declare another in the stream header."""
    h = opened(rate=open_rate)
    h.send(OP_FEED, opcm_header(CHANNELS, header_rate))
    h.drain()
    for i in range(4):
        h.send(OP_FEED, opcm_tone(BLOCK, len(CHANNELS), header_rate, start=i * BLOCK))
        h.drain()
    h.send(OP_CLOSE)
    rc, _ = h.finish()
    return h, rc


# Agreement: the ordinary case, and the one that proves the field is not simply
# echoing back what the helper was told to open at - the check below only means
# something because this one passes for a different reason.
h, rc = run_at(48000, 48000)
check(rc == 0 and reported_rate(h) == 48000, "a 48 kHz stream is reported as 48 kHz",
      f"rc={rc} rate={reported_rate(h)}")

# Disagreement: the whole point. This is the shape of DTS-HD MA with a 96 kHz
# XLL extension over a 48 kHz core - the host reads the core sync word, opens
# the engine at 48000, and the bridge decodes at 96000. Nothing downstream can
# notice: the film simply plays at half speed for its whole length. The helper
# has to report what was decoded, not what it was asked for.
h, rc = run_at(48000, 96000)
opened_at = [t for t in (t for c, t in h.status if c == ST_OK) if t.startswith("open ")]
check(reported_rate(h) == 96000,
      "a 96 kHz stream opened at 48 kHz is reported as 96 kHz",
      f"rate={reported_rate(h)} while {opened_at[0] if opened_at else '?'}")
check(any("rate=48000" in t for t in opened_at) and reported_rate(h) != 48000,
      "so the two rates are distinguishable, which is what the host acts on")

# bed= has to stay last on the line: the host reads it to the end of the line
# rather than to the next space, because a bed is a comma-separated list. A new
# key appended after it would be swallowed into the bed name.
lines = stream_lines(h)
check(bool(lines) and all(t.rfind("bed=") > t.rfind("rate=") for t in lines),
      "rate= comes before bed=, so bed= is still read to end of line",
      lines[-1] if lines else "no stream line")

print()
print("=" * 74)
passed = sum(1 for _, ok in results if ok)
print(f" {passed}/{len(results)} checks passed")
print("=" * 74)
sys.exit(0 if passed == len(results) else 1)
