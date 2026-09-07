#!/bin/bash
# Rebuild the prebuilt BD-J jars in jars/ from the patched libbluray source.
#
# These jars are NOT compiled by the image build - package.mk copies them
# verbatim - so a patch touching src/libbluray/bdj/**/*.java changes nothing
# until this script is run and the result committed. Run it after any such
# patch, and assert on the artifact afterwards (see VERIFY below).
#
# Must be built with a real JDK 8. The BD-J tree overrides JDK-internal
# classes (java.io.BDFileSystem hooks java.io.File, the java.awt peers) and
# calls methods that exist in Java 8 and not in later releases. A modern javac
# with -source/-target 1.8 emits correct major=52 bytecode but still resolves
# against its own platform classes, so it is NOT equivalent.
#
# Usage: rebuild-bdj-jars.sh <patched-libbluray-source-dir> [jdk8-home]

set -euo pipefail

SRC="${1:?usage: rebuild-bdj-jars.sh <patched-libbluray-source-dir> [jdk8-home]}"
SRC="$(cd "$SRC" && pwd)"   # absolute: the build cd's into the bdj tree
JDK="${2:-${JDK8_HOME:-}}"
HERE="$(cd "$(dirname "$0")" && pwd)"
BDJ="$SRC/src/libbluray/bdj"

[ -d "$BDJ/java" ] || { echo "not a libbluray source tree: $SRC" >&2; exit 1; }
[ -n "$JDK" ] && [ -x "$JDK/bin/javac" ] || {
  echo "need a JDK 8: pass its home as \$2 or set JDK8_HOME" >&2; exit 1; }

JV="$("$JDK/bin/javac" -version 2>&1)"
case "$JV" in *" 1.8."*) ;; *) echo "refusing: need JDK 8, got '$JV'" >&2; exit 1;; esac

VERSION="$(sed -n "s/^ *version *: *'\([0-9.]*\)'.*/\1/p" "$SRC/meson.build" | head -1)"
[ -n "$VERSION" ] || { echo "could not read version from meson.build" >&2; exit 1; }
echo "libbluray $VERSION, $JV"

W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
mkdir -p "$W/classes"

# Mirrors src/libbluray/bdj/build.xml: two javac passes into one tree, then
# split into the core jar and the java.awt/sun jar.
cd "$BDJ"
find "$SRC/contrib/asm/src" -name '*.java' > "$W/asm.list"
"$JDK/bin/javac" -d "$W/classes" -g -encoding UTF-8 -XDignore.symbol.file -nowarn @"$W/asm.list"
find java java-j2se java-build-support -name '*.java' > "$W/bdj.list"
"$JDK/bin/javac" -d "$W/classes" -g -encoding UTF-8 -XDignore.symbol.file -nowarn \
  -cp "$W/classes" -sourcepath "java:java-j2se:java-build-support" @"$W/bdj.list"

cd "$W/classes"
find . -name '*.class' | sed 's|^\./||' | grep -vE '^(java/awt/|sun/)' > "$W/j1.list"
find . -name '*.class' | sed 's|^\./||' | grep -E '^(java/awt/|sun/)' \
  | grep -vE '^sun/awt/CausedFocusEvent|^java/awt/event/FocusEvent' > "$W/j2.list"

"$JDK/bin/jar" cf "$HERE/jars/libbluray-j2se-$VERSION.jar"     @"$W/j1.list"
"$JDK/bin/jar" cf "$HERE/jars/libbluray-awt-j2se-$VERSION.jar" @"$W/j2.list"

echo "wrote:"; ls -la "$HERE/jars/"
echo
echo "VERIFY: confirm your .java patches are in the ARTIFACT, not just the source."
echo "  unzip -p jars/libbluray-j2se-$VERSION.jar <class> | cmp - <expected>   or"
echo "  read the method's access flags / bytecode out of the class file."
