# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026-present samurihl

PKG_NAME="samurihl-update"
PKG_VERSION="1.3.0"
PKG_LICENSE="GPL-3.0-or-later"
PKG_SITE="https://github.com/bokkoman/samurihl_ce_auto_update_addon"
PKG_URL=""
PKG_DEPENDS_TARGET="toolchain"
PKG_LONGDESC="Update checker for samurihl CoreELEC builds (service.samurihl.coreelec.update), written by bokkoman."
PKG_TOOLCHAIN="manual"

makeinstall_target() {
  mkdir -p ${INSTALL}/usr/share/kodi/addons
    cp -R ${PKG_DIR}/source/service.samurihl.coreelec.update ${INSTALL}/usr/share/kodi/addons
}
