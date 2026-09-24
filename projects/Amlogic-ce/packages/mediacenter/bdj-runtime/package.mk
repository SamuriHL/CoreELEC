# SPDX-License-Identifier: GPL-2.0-or-later

PKG_NAME="bdj-runtime"
PKG_VERSION="1"
PKG_LICENSE="LGPL"
PKG_URL=""
PKG_DEPENDS_TARGET="toolchain jre-libbluray"
PKG_LONGDESC="Matching libbluray Java classes for the image's native BD-J library"
PKG_TOOLCHAIN="manual"

makeinstall_target() {
  local bluray_version="$(get_pkg_version libbluray)"
  local jars="$(get_install_dir jre-libbluray)/usr/share/java"

  # Use the same patched source as native libbluray. Fail packaging if either
  # half is absent; an installed JRE addon's older classes are not a substitute.
  test -s "${jars}/libbluray-j2se-${bluray_version}.jar" || return 1
  test -s "${jars}/libbluray-awt-j2se-${bluray_version}.jar" || return 1
  mkdir -p "${INSTALL}/usr/share/java"
  cp "${jars}/libbluray-j2se-${bluray_version}.jar" \
     "${jars}/libbluray-awt-j2se-${bluray_version}.jar" "${INSTALL}/usr/share/java/"

  mkdir -p "${INSTALL}/usr/lib/coreelec"
  echo 'export LIBBLURAY_CP=/usr/share/java/' > "${INSTALL}/usr/lib/coreelec/bdj-runtime.sh"
}
