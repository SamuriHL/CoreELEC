# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2023-present Team CoreELEC (https://coreelec.org)
#
# SamuriHL CE22 OVERRIDE (Smart CMv4.0 feature). Upstream has since adopted
# libdovi 3.4.0 and its own from-source path, so this file is now upstream's
# verbatim except for the forced BUILD_FROM_SRC below.
#
# WHY THE FORCE: our Smart CMv4.0 feature needs patches/0001-rpu-synthesise-L8-
# trims-*.patch, which can only apply to a source build. Upstream's prebuilt
# branch ships an unpatched libdovi, and BUILD_FROM_SRC is set NOWHERE else in
# this tree (it appears only in this file), so without this line the default
# path silently drops the L8-trim synthesis and the DM pins the neutral tone
# curve. Verified identical source: the from-source tarball sha256 below is
# byte-identical to the libdovi-3.4.0 archive the fork already builds.
BUILD_FROM_SRC="yes"

PKG_NAME="libdovi"
PKG_VERSION="3.4.0"
PKG_SITE="https://github.com/quietvoid/dovi_tool"
PKG_DEPENDS_TARGET="toolchain"
if [ "${BUILD_FROM_SRC}" = "yes" ]; then
  PKG_SHA256="8eac4d1c3134f53e8eb216db6450307a737425844113e480d1e9713c142a9fa2"
  PKG_URL="https://github.com/quietvoid/dovi_tool/archive/${PKG_NAME}-${PKG_VERSION}.tar.gz"
  PKG_DEPENDS_TARGET+=" cargo-c:host"
else
  PKG_SHA256="aba1f67f713ff1838478d09d442b1047a75f34024fe42d96aeff2917bbc8e70e"
  PKG_SOURCE_NAME="${PKG_NAME}-${ARCH}-${PKG_VERSION}.tar.xz"
  PKG_URL="https://sources.coreelec.org/${PKG_SOURCE_NAME}"
fi
PKG_LICENSE="MIT"
PKG_LONGDESC="dovi_tool is a CLI tool combining multiple utilities for working with Dolby Vision."
PKG_TOOLCHAIN="manual"

if [ "${BUILD_FROM_SRC}" = "yes" ]; then
pre_make_target() {
  CARGO_BASE_OPTS="--manifest-path ${PKG_BUILD}/dolby_vision/Cargo.toml \
                   --target ${TARGET_NAME}"
  CARGO_BUILD_OPTS="--library-type staticlib \
                    --profile release \
                    --prefix /usr \
                    ${CARGO_BASE_OPTS}"
}

make_target() {
  cargo fetch ${CARGO_BASE_OPTS}
  cargo cbuild ${CARGO_BUILD_OPTS}
}

makeinstall_target() {
  cargo cinstall ${CARGO_BUILD_OPTS} --destdir ${SYSROOT_PREFIX}
  cargo cinstall ${CARGO_BUILD_OPTS} --destdir ${INSTALL}
}
else
make_target() {
  cp -PR * ${SYSROOT_PREFIX}
}

makeinstall_target() {
  : #
}
fi
