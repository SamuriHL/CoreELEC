# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2023-present Team CoreELEC (https://coreelec.org)
#
# SamuriHL CE22 OVERRIDE (Smart CMv4.0 feature): stock CE22 uses a prebuilt
# libdovi 3.3.1 which lacks the CMv4.0 append/remove + unspec62 C API. Those
# functions are merged into quietvoid/dovi_tool main but not yet in a tagged
# libdovi release, so we pin a main commit and ALWAYS build from source.
# The first such build also bootstraps rust:host (~1-2h, cached after).
# Commit 4b7b9d2 exports: dovi_parse_unspec62_nalu / dovi_write_unspec62_nalu /
# dovi_rpu_add_cmv40_safe_default_metadata / dovi_rpu_remove_cmv40_metadata.

PKG_NAME="libdovi"
PKG_VERSION="4b7b9d236cfcd4908a15dd18a7a7db53dba6b7d2"
PKG_SHA256="d516c7312e3c98c64891c302ffcedab71f7ba9a8af48cfe8fac4b3f9d355ba07"
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
