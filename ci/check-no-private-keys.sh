#!/bin/sh
# Fails when a tracked file holds private key material. Only public keys
# belong in this repository; the release signing key is a CI secret.
set -eu
status=0
if git grep -nIE -e '-----BEGIN ([A-Z0-9]+ )*PRIVATE KEY( BLOCK)?-----'; then
	status=1
fi
if git ls-files | grep -E '(^|/)(secring\.gpg|private-keys-v1\.d/)'; then
	status=1
fi
[ "$status" -eq 0 ] || echo "private key material is tracked; remove it and rotate the key" >&2
exit "$status"
