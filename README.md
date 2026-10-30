# openmediavault-garage

OpenMediaVault 8 plugin for [Garage](https://garagehq.deuxfleurs.fr), the
S3-compatible self-hosted object storage by Deuxfleurs. This replaces the
removed `openmediavault-s3` (MinIO) plugin with a native, non-containerized
implementation.

The plugin manages **multiple Garage instances** on one OMV box. Each
instance is a systemd template unit instance (`garage@<name>.service`,
shipped by the `garage` Debian package) that runs under a dedicated
unprivileged `garage` user with systemd sandboxing.

## Features

- N instances, each with:
  - N datastores, picked from OMV shared folders, each with a layout capacity
  - buckets with quotas and optional S3 website hosting
  - access keys (created or imported)
  - per key and bucket read/write/owner permissions
- Buckets, keys and permissions live only in garage. The plugin reads and
  changes them through the instance's admin API, so changes made in the
  web UI or by S3 clients show up at once and nothing can drift.
- Always-on listeners: S3 API (all interfaces), internal RPC and admin API
  (loopback)
- Optional website hosting listener (all interfaces)
- Unused ports are pre-suggested when creating an instance; duplicate ports
  on create are silently resolved to the next free port
- Optional vendored community web UI (khairul169/garage-webui, MIT), disabled
  by default, reachable only through the authenticated OMV web interface with
  one-click sign-in (no password prompt, credentials never leave the server
  side of OMV)

## Install

```sh
apt install ./openmediavault-garage_0.1.0-1_amd64.deb
```

Requires the `garage` package (see the `garage-debian` repo). Then find the
plugin under **Services > Garage**.

Workflow per instance:

1. Create an instance: name, ports, storage shared folder. A storage folder
   alone is one data folder and needs no capacity.
2. Optionally add datastores (shared folders + capacity in GiB). Garage then
   needs a capacity on every data folder, so the instance also needs its
   storage folder capacity. Capacities are placement weights, not limits.
   With a separate metadata shared folder the data lives on datastores
   only, so such an instance can be enabled once it has one. A datastore's
   shared folder cannot be changed later, only its capacity.
3. Apply the pending configuration changes (top bar checkmark). The salt
   deploy renders `/etc/garage/<name>.toml`, the systemd drop-in, ACLs, and
   starts `garage@<name>`, then bootstraps the single-node layout with the
   sum of the capacities (1 TiB without datastores).
4. Create buckets, keys and permissions in the instance's details view.
   These take effect at once in the running instance, with no apply.
5. Point S3 clients at `http://<omv>:<s3port>` with the region and a key.

Removing a datastore takes two deletes. After the first delete and an
apply, the datastore is read-only and Garage moves its blocks to the other
data folders. Objects stay readable meanwhile. The **Status** column of the
**Datastores** tab shows how many block files are left (counted up to
10000). Garage keeps this move in memory only, and ends it with blocks
left when it cannot write them. So `garage@<name>` starts it again after
every start, including a reboot, and every apply starts it again unless
one is running. Once the status says the datastore is empty, delete it
again and apply. That apply drops the folder from the instance, removes
the empty directories and the marker Garage left in it, and revokes the
folder's ACL. The last datastore of an enabled instance with a separate
metadata folder cannot be removed.

Deleting an instance only removes it from the configuration. The apply
stops its units, removes its files and revokes its folders' ACLs, so
undoing the pending change instead leaves the instance running as it was.
Disabling an instance does the same on apply, except that its folders keep
their data and their ACLs. Enabling it again renders its files from the
configuration, and it starts with its buckets, keys and objects.

The plugin only touches what it rendered. Every toml it writes carries
the line `# Managed by openmediavault-garage.`, and an apply or a package
removal only cleans up an instance whose toml has it. An instance written
by hand next to them, as the garage README describes, is left alone.

## Security model

- Garage and the web UI run as the system user `garage` (no shell), with
  `ProtectSystem=strict`, `NoNewPrivileges`, system-call filtering, and
  per-instance `ReadWritePaths` limited to the chosen shared folders.
- Configs and secrets live in `/etc/garage/` (0600/0640, `root:garage`).
- The user `garage` gets an ACL entry on each shared folder an instance
  uses. It is `rwx` where Garage writes into the folder itself (a
  datastore, or metadata or snapshots at the folder's root), and `--x` where
  Garage only enters the directories the deploy made for it (the storage
  folder, a separate metadata folder). The deploy records each folder it
  grants in `/var/lib/openmediavault-garage/acls.json` before it grants,
  and each apply revokes the entry only from recorded folders no instance
  uses. A `garage` entry the admin set by hand, for example for a
  hand-made instance, stays. Purging the package revokes the recorded
  entries.
- RPC, admin API and web UI bind to loopback only. Only the S3 API (and the
  optional website port) listen on the network.
- The web UI is proxied by the OMV nginx and requires an OMV admin session;
  sign-in happens same-origin so the browser never talks to the web UI port
  directly.
- The web UI password is generated automatically (24 chars). The plaintext is
  stored in the OMV configuration database so one-click sign-in works; the
  same trust model OMV already uses for stored TLS private keys. Regenerate
  it via `omv-rpc -u admin Garage renewWebUiPassword '{"uuid":"..."}'`.

## Build

```sh
make dist/.built    # dist/openmediavault-garage_0.1.0-1_amd64.deb
```

The package version comes from the top entry of `debian/changelog`. The
build downloads nfpm from its pinned GitHub release into `.tools/` and
checks it against `checksums/nfpm_*.sha256`; to move to a new nfpm, change
`NFPM_VERSION` in the `Makefile` and commit the sha256 of the new
`Linux_x86_64` tarball from the release's `checksums.txt`. The vendored
webui binary is checksum-pinned in `checksums/` and verified at build time.
`./build.sh` alone uses `nfpm` from `PATH`, or `$NFPM`.

## Test

```sh
make check          # actionlint, shellcheck, php -l, yamllint, no private keys tracked
make unit           # PHPUnit in php:8.4-cli (Docker)
make lint           # builds dist/ if needed, then trixie's lintian (Docker)
make package-test   # make lint, then pytest checks on the deb (Docker)
make e2e            # Playwright suite against a real OMV host
tests/lifecycle.sh root@omv-test.lan dist/openmediavault-garage_0.1.0-1_amd64.deb
```

`make check`, `make unit`, `make lint` and `make package-test` need no VM. Each lintian
override in `tree/usr/share/lintian/overrides/` carries its reason. `make e2e` reads
`OMV_HOST`, `OMV_SSH`, `OMV_ADMIN_PASSWORD` and `OMV_DISK` from the
environment; see `tests/e2e/README.md`. Pass extra test-runner arguments
with `ARGS`, for example `make package-test ARGS=--runxfail`.

`tests/lifecycle.sh` installs the deb on an OMV host over ssh, upgrades
it to a repacked higher version, removes it, reinstalls it and purges it,
checking the engine restarts, the instances, files, confdb, ACLs and the
workbench after each step. Purge forgets every instance in confdb, so it
refuses to run while the host has instances other than its own throwaway
`gt<hex>` ones unless you pass `--force`. Instance data is never deleted.
The host keeps the tested deb installed.

## CI

`.github/workflows/build.yml` runs `make check`, `make unit` and
`make package-test` on every push and pull request, the same commands as
above. Each tool runs in a container pinned in one place: the PHP,
Composer and actionlint images and nfpm in the `Makefile`; trixie's lintian,
shellcheck, yamllint and dpkg-dev plus uv in `ci/tools.Dockerfile`. Actions
are pinned by commit SHA. The e2e suite and `tests/lifecycle.sh` need the
OMV VM and stay local.

## Release

Push a tag `v<version>-<release>` that equals the top `debian/changelog`
entry, for example `v0.1.0-1`, or `v0.1.0-2` for a packaging-only fix. CI
fails when the tag and the changelog disagree. After the checks pass, the
`sign` job writes `SHA256SUMS` for the deb and a detached signature
`SHA256SUMS.asc` with the key in the `GPG_PRIVATE_KEY` secret (passphrase
in `GPG_PASSPHRASE`, optional), and checks it against `keys/`. The
`publish` job attaches the deb, `SHA256SUMS` and `SHA256SUMS.asc` to the
GitHub release. Only `sign` sees the secrets, and only `publish` can write
to the repository. Pull requests never reach either job.

Verify a download:

```sh
gpg --import keys/release-signing-test.asc
gpg --verify SHA256SUMS.asc SHA256SUMS
sha256sum -c SHA256SUMS
```

The key in `keys/` is a test key; see `keys/README.md`.

## Layout

- `tree/usr/share/openmediavault/datamodels/` - config + RPC schemas
- `tree/usr/share/openmediavault/engined/rpc/garage.inc` - RPC service
- `tree/usr/share/openmediavault/engined/module/garage.inc` - deploy module
- `tree/srv/salt/omv/deploy/garage/` - salt state: toml, secrets, drop-ins,
  ACLs, units, nginx locations, orphan cleanup
- `tree/usr/share/openmediavault/garage/lib/render.php` - the render model:
  every path, data folder, port, ACL and the layout capacity of an
  instance; `render-instances.php` prints it for every instance as JSON for
  the salt state, with the deleted or disabled instances and the ACLs to
  revoke
- `tree/usr/share/openmediavault/garage/lib/owned.php` - what the plugin
  owns: tomls with its marker line and the ACLs it recorded
- `tree/usr/share/openmediavault/garage/lib/drain.php` - when a draining
  datastore is empty; `start-rebalance.sh` restarts the move after a start
  and on every apply
- `tree/usr/share/openmediavault/garage/bootstrap-instance.php` - idempotent
  single-node layout bootstrap (wait, assign, apply, converge capacity)
- `tree/var/www/openmediavault/garage-sso/` - one-click web UI sign-in page,
  and `auth.php`, the nginx `auth_request` check that lets only OMV admin
  sessions through to the web UI
- `tree/usr/lib/systemd/system/omv-garage-webui@.service` - web UI template,
  running the vendored `/usr/libexec/openmediavault-garage/garage-webui`
- `debian/changelog` - package version and history, shipped as
  `changelog.Debian.gz`

## License

GPL-3, copyright bor. The vendored web UI is MIT, copyright Khairul Hidayat.
Garage is AGPL-3, copyright Deuxfleurs and the Garage contributors. See
`tree/usr/share/doc/openmediavault-garage/copyright`.
