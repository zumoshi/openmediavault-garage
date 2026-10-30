#!/bin/sh
set -eu

usage() {
	cat <<EOF
Usage:
  $0                                   build the plugin deb at the debian/changelog version
  WEBUI_VERSION=1.1.0 $0 record        pin the webui checksum
EOF
	exit 2
}

WEBUI_VERSION=${WEBUI_VERSION:-1.1.0}
WEBUI_URL="https://github.com/khairul169/garage-webui/releases/download/${WEBUI_VERSION}/garage-webui-v${WEBUI_VERSION}-linux-amd64"

download_webui() {
	mkdir -p tree/usr/libexec/openmediavault-garage
	_sumfile="checksums/webui-${WEBUI_VERSION}.amd64.sha256"
	if [ -f tree/usr/libexec/openmediavault-garage/garage-webui ] && [ -f "$_sumfile" ]; then
		_actual=$(sha256sum tree/usr/libexec/openmediavault-garage/garage-webui | awk '{print $1}')
		if [ "$_actual" = "$(cat "$_sumfile")" ]; then
			echo "garage-webui already matches ${_sumfile}"
			return
		fi
	fi
	echo "downloading ${WEBUI_URL}"
	curl -fsSL -o tree/usr/libexec/openmediavault-garage/garage-webui "$WEBUI_URL"
	chmod 0755 tree/usr/libexec/openmediavault-garage/garage-webui
}

case "${1:-build}" in
record)
	download_webui
	sha256sum tree/usr/libexec/openmediavault-garage/garage-webui \
		| awk '{print $1}' > "checksums/webui-${WEBUI_VERSION}.amd64.sha256"
	echo "pinned checksums/webui-${WEBUI_VERSION}.amd64.sha256"
	;;
build)
	changelog_version=$(sed -n '1s/^openmediavault-garage (\(.*\)).*/\1/p' debian/changelog)
	VERSION=${VERSION:-${changelog_version%-*}}
	RELEASE=${RELEASE:-${changelog_version##*-}}
	[ "${VERSION}-${RELEASE}" = "$changelog_version" ] || {
		echo "debian/changelog is at ${changelog_version}; add an entry for ${VERSION}-${RELEASE}" >&2
		exit 1
	}
	download_webui
	sumfile="checksums/webui-${WEBUI_VERSION}.amd64.sha256"
	[ -f "$sumfile" ] || {
		echo "missing ${sumfile}; run '$0 record' once and commit it" >&2
		exit 1
	}
	expected=$(cat "$sumfile")
	actual=$(sha256sum tree/usr/libexec/openmediavault-garage/garage-webui | awk '{print $1}')
	[ "$actual" = "$expected" ] || {
		echo "webui checksum mismatch" >&2
		exit 1
	}
	gzip -9nc debian/changelog >tree/usr/share/doc/openmediavault-garage/changelog.Debian.gz
	mkdir -p dist
	export VERSION RELEASE
	nfpm package -f nfpm.yaml -p deb \
		-t "dist/openmediavault-garage_${VERSION}-${RELEASE}_amd64.deb"
	;;
*)
	usage
	;;
esac
