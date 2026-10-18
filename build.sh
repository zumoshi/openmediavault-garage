#!/bin/sh
set -eu

usage() {
	cat <<EOF
Usage:
  VERSION=8.0.1 [RELEASE=1] $0          build the plugin deb
  VERSION=1.1.0 $0 record               pin the webui checksum
EOF
	exit 2
}

WEBUI_VERSION=${WEBUI_VERSION:-1.1.0}
WEBUI_URL="https://github.com/khairul169/garage-webui/releases/download/${WEBUI_VERSION}/garage-webui-v${WEBUI_VERSION}-linux-amd64"

download_webui() {
	mkdir -p tree/usr/share/openmediavault/garage/bin
	echo "downloading ${WEBUI_URL}"
	curl -fsSL -o tree/usr/share/openmediavault/garage/bin/garage-webui "$WEBUI_URL"
	chmod 0755 tree/usr/share/openmediavault/garage/bin/garage-webui
}

case "${1:-build}" in
record)
	download_webui
	sha256sum tree/usr/share/openmediavault/garage/bin/garage-webui \
		| awk '{print $1}' > "checksums/webui-${WEBUI_VERSION}.amd64.sha256"
	echo "pinned checksums/webui-${WEBUI_VERSION}.amd64.sha256"
	;;
build)
	VERSION=${VERSION:?VERSION required, e.g. 8.0.1}
	RELEASE=${RELEASE:-1}
	download_webui
	sumfile="checksums/webui-${WEBUI_VERSION}.amd64.sha256"
	[ -f "$sumfile" ] || {
		echo "missing ${sumfile}; run '$0 record' once and commit it" >&2
		exit 1
	}
	expected=$(cat "$sumfile")
	actual=$(sha256sum tree/usr/share/openmediavault/garage/bin/garage-webui | awk '{print $1}')
	[ "$actual" = "$expected" ] || {
		echo "webui checksum mismatch" >&2
		exit 1
	}
	mkdir -p dist
	VERSION="$VERSION" RELEASE="$RELEASE" \
		nfpm package -f nfpm.yaml -p deb \
		-t "dist/openmediavault-garage_${VERSION}-${RELEASE}_all.deb"
	;;
*)
	usage
	;;
esac
