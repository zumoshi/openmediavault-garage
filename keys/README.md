# Release signing keys

`release-signing-test.asc` is a TEST key (ed25519, fingerprint
`400F DB85 AEEF 67A2 A02D  085F 992C 7900 82DF 7A2B`). Its private half was
generated for local `act` runs and is kept outside this repository, so a
signature from it proves nothing about who built a release. CI checks every
release signature against the public keys in this directory. Before
publishing releases that users should trust, add the real public key here,
delete this file, and store the real private key in the `GPG_PRIVATE_KEY`
secret.
