#!/bin/sh
# Writes SHA256SUMS for the debs in <dir> and a detached, ASCII-armored
# SHA256SUMS.asc made with the secret key in $GPG_PRIVATE_KEY (passphrase
# in $GPG_PASSPHRASE, if any), then verifies the signature against the
# public keys committed in keys/.
set -eu
[ $# -eq 1 ] || {
	echo "usage: GPG_PRIVATE_KEY=... [GPG_PASSPHRASE=...] $0 <dir>" >&2
	exit 2
}
: "${GPG_PRIVATE_KEY:?is not set}"
keys=$(cd "$(dirname "$0")/../keys" && pwd)
cd "$1"
rm -f SHA256SUMS SHA256SUMS.asc
sha256sum -- *.deb >SHA256SUMS

signing=$(mktemp -d)
verifying=$(mktemp -d)
trap 'gpgconf --homedir "$signing" --kill all; gpgconf --homedir "$verifying" --kill all; rm -rf "$signing" "$verifying"' EXIT

printf '%s\n' "$GPG_PRIVATE_KEY" | gpg --homedir "$signing" --batch --import
printf '%s' "${GPG_PASSPHRASE:-}" | gpg --homedir "$signing" --batch --yes \
	--pinentry-mode loopback --passphrase-fd 0 \
	--armor --detach-sign --output SHA256SUMS.asc SHA256SUMS

gpg --homedir "$verifying" --batch --import "$keys"/*.asc
gpg --homedir "$verifying" --batch --verify SHA256SUMS.asc SHA256SUMS
sha256sum -c SHA256SUMS
