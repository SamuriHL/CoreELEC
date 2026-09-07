# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2009-2016 Stephan Raue (stephan@openelec.tv)
# Copyright (C) 2018-present Team LibreELEC (https://libreelec.tv)

PKG_NAME="libbluray"
PKG_VERSION="1.5.0"
PKG_SHA256="7a5d945a9c2b0064a748b77a4c5ab563175bb7219e9d562b2b2399790726a388"
PKG_LICENSE="LGPL-2.1-or-later"
PKG_SITE="https://www.videolan.org/developers/libbluray.html"
# Deliberately the TAG ARCHIVE, not the release tarball on download.videolan.org
# (which does now exist - an older comment here claimed otherwise). Two reasons:
#  - our all-001/all-002 patch pair is regenerated against this archive; upstream's
#    pair is regenerated against theirs, and mixing them rejects hunks in bluray.h.
#  - the tag export leaves contrib/libudfread EMPTY, so -Dembed_udfread=true
#    resolves libudfread from the sysroot (the version in PKG_DEPENDS_TARGET).
#    The release tarball ships contrib/libudfread populated and would embed the
#    bundled copy instead, silently swapping the UDF implementation under the
#    whole Blu-ray disc path. Every file the two share is byte-identical.
# Switching to the release tarball means taking upstream's patch pair with it,
# and testing the resulting disc path - a change of its own, not a drive-by.
PKG_URL="https://code.videolan.org/videolan/${PKG_NAME}/-/archive/${PKG_VERSION}/${PKG_NAME}-${PKG_VERSION}.tar.gz"
PKG_DEPENDS_TARGET="toolchain fontconfig freetype libxml2 libudfread"
PKG_LONGDESC="libbluray is an open-source library designed for Blu-Ray Discs playback for media players."

if [ "${BLURAY_AACS_SUPPORT}" = "yes" ]; then
  PKG_DEPENDS_TARGET+=" libaacs"
fi

if [ "${BLURAY_BDPLUS_SUPPORT}" = "yes" ]; then
  PKG_DEPENDS_TARGET+=" libbdplus"
fi

PKG_MESON_OPTS_TARGET="-Ddefault_library=shared \
                       -Denable_docs=false \
                       -Denable_tools=false \
                       -Denable_devtools=false \
                       -Denable_examples=false \
                       -Dbdj_jar=disabled \
                       -Dembed_udfread=true \
                       -Dfontconfig=enabled \
                       -Dfreetype=enabled \
                       -Dlibxml2=enabled"

# Ship the version-matched BD-J jars in the image (/usr/share/java is in
# libbluray's default jar search list). The native lib only loads the jar of
# its EXACT version; the tools.jre.zulu addon carries jars for older
# libbluray, and its LIBBLURAY_CP override is handled by the
# libbluray-03-bdj-fallback patch so stale addon jars can no longer kill
# BD-J. Jars are arch-independent and built from this same source tree by
# rebuild-bdj-jars.sh, which needs a real JDK 8: the BD-J tree overrides
# JDK-internal classes and calls methods that later releases removed, so a
# modern javac with -source/-target 1.8 emits the right bytecode version while
# still resolving against its own platform classes. They are NOT built by the
# image build - the copy below is verbatim - so a patch touching
# src/libbluray/bdj/**/*.java changes NOTHING until the jars are rebuilt and
# committed. Rebuild on a version bump AND on every Java-side patch, then
# assert the change is in the artifact, not just in the patched source.
post_makeinstall_target() {
  mkdir -p ${INSTALL}/usr/share/java
  cp ${PKG_DIR}/jars/libbluray-j2se-${PKG_VERSION}.jar \
     ${PKG_DIR}/jars/libbluray-awt-j2se-${PKG_VERSION}.jar \
     ${INSTALL}/usr/share/java/
}
