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
PKG_DEPENDS_TARGET="toolchain fontconfig freetype libxml2 libudfread apache-ant:host"
PKG_DEPENDS_UNPACK="jdk-${MACHINE_HARDWARE_NAME}-zulu"
# PKG_DEPENDS_UNPACK does NOT feed calculate_stamp - it hashes $PKG_DIR, the
# patch dirs and PKG_NEED_UNPACK only. Without this, bumping the Zulu JDK or
# apache-ant leaves libbluray's deephash unchanged, the build is skipped, and
# the PREVIOUSLY BUILT jar is reinstalled into the image with nobody told:
# the "patches sat inert for weeks" failure, one level up. Worse, build.xml's
# chain is dist -> compile -> init with no clean, ${build} is meson's
# persistent @PRIVATE_DIR@, and <javac> is incremental - so a surviving build
# dir across a JDK change repacks stale .class files into a jar mixing class
# file versions, which throws UnsupportedClassVersionError on the box's Zulu 8
# runtime. Same idiom as packages/graphics/glu/package.mk.
PKG_NEED_UNPACK="$(get_pkg_directory jdk-${MACHINE_HARDWARE_NAME}-zulu) $(get_pkg_directory apache-ant)"
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
                       -Dbdj_jar=enabled \
                       -Dembed_udfread=true \
                       -Dfontconfig=enabled \
                       -Dfreetype=enabled \
                       -Dlibxml2=enabled"

# Build the BD-J jars from this same (patched) source tree on every build and
# let meson install them to /usr/share/java, which is in libbluray's default
# jar search list. The native lib only loads the jar of its EXACT version.
#
# These used to be prebuilt artifacts committed under jars/ and copied verbatim
# here, which meant a patch touching src/libbluray/bdj/**/*.java applied to the
# source and then shipped nothing. Two patches sat inert that way for weeks.
# There is deliberately no prebuilt copy any more: nothing that can go stale.
#
# The jars MUST be built by a real JDK 8. The BD-J tree overrides JDK-internal
# classes (java.io.BDFileSystem hooks java.io.File, the java.awt peers) and
# calls methods later releases removed, so a modern javac with -source/-target
# 1.8 emits the right bytecode version while still resolving against its own
# platform classes - not equivalent. libbluray's own meson picks the oldest
# -source its javac still supports (1.4 under JDK 8), so the toolchain also
# decides the bytecode level; pinning JDK 8 pins that too.
#
# jdk-${MACHINE_HARDWARE_NAME}-zulu is the same Zulu 8 the tools.jre.zulu addon
# ships as the runtime, so the jars are built and executed by the same Java.
pre_configure_target() {
  local _jdk="$(get_build_dir jdk-${MACHINE_HARDWARE_NAME}-zulu)"
  export JAVA_HOME="${_jdk}"
  export PATH="${_jdk}/bin:${PATH}"
  PKG_MESON_OPTS_TARGET+=" -Djdk_home=${_jdk}"
}
