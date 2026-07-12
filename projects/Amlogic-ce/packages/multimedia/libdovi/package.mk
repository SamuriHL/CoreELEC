# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2023-present Team CoreELEC (https://coreelec.org)
#
# SamuriHL CE22 OVERRIDE (Smart CMv4.0 feature): stock CE22 uses a prebuilt
# libdovi 3.3.1 which lacks the CMv4.0 append/remove + unspec62 C API. As of
# libdovi 3.4.0 (tag libdovi-3.4.0, commit d1abe0e2) everything we need is in
# a tagged release, so we pin the release tag and ALWAYS build from source.
# The first such build also bootstraps rust:host (~1-2h, cached after).
# 3.4.0 exports all C APIs used by the fork: dovi_parse_unspec62_nalu /
# dovi_write_unspec62_nalu / dovi_rpu_add_cmv40_safe_default_metadata /
# dovi_rpu_remove_cmv40_metadata / dovi_rpu_set_active_area_offsets etc.

PKG_NAME="libdovi"
PKG_VERSION="libdovi-3.4.0"
PKG_SHA256="8eac4d1c3134f53e8eb216db6450307a737425844113e480d1e9713c142a9fa2"
PKG_LICENSE="MIT"
PKG_SITE="https://github.com/quietvoid/dovi_tool"
PKG_URL="https://github.com/quietvoid/dovi_tool/archive/${PKG_VERSION}.tar.gz"
PKG_DEPENDS_TARGET="toolchain cargo-c:host"
PKG_LONGDESC="dovi_tool utilities for Dolby Vision (CE22 CMv4.0-append build from source)."
PKG_TOOLCHAIN="manual"

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
