#!/bin/sh
set -eu
apt-get update
apt-get upgrade -y
apt-get install -y --no-install-recommends build-essential dpkg-dev debhelper dh-exec autotools-dev autoconf automake libtool pkgconf gettext bison flex libaudit-dev libcap-ng-dev libcrypt-dev libncurses-dev libpam0g-dev libreadline-dev libselinux1-dev libsqlite3-dev libsystemd-dev systemd-dev libudev-dev zlib1g-dev po-debconf po4a libattr1-dev libgpm-dev autoconf-dickey ncurses-term ca-certificates
export DEB_BUILD_OPTIONS='parallel=4 nocheck nodoc'
export DEB_BUILD_PROFILES='nocheck nodoc pkg.util-linux.noverity nobiarch'
# Package builders include privileged/system integration tests. These are not
# claimed here; unprivileged upstream checks and application acceptance are
# separately recorded in the release receipt.
