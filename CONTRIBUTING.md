# Contributing to openmediavault-garage

This file is for people building, testing, or releasing the plugin. For
installing and using it, see [README.md](README.md).

## Building

```sh
make dist/.built    # dist/openmediavault-garage_0.1.0-1_amd64.deb
```

The package version comes from the top entry of `debian/changelog`. The build
downloads nfpm from its pinned GitHub release into `.tools/` and checks it
against `checksums/nfpm_*.sha256`. To move to a new nfpm, change
`NFPM_VERSION` in the `Makefile` and commit the sha256 of the new
`Linux_x86_64` tarball from the release's `checksums.txt`. The build pins
the web UI binary in `checksums/` and verifies it at build time. `./build.sh`
alone uses `nfpm` from `PATH`, or `$NFPM`.

The deb is `amd64` because the vendored web UI binary is `amd64`. Upstream
Garage and garage-webui both publish arm64, so an arm64 build is possible but
not wired up yet.

## Testing

```sh
make check          # actionlint, shellcheck, php -l, yamllint, no private keys tracked
make unit           # PHPUnit in a php:8.4-cli container
make lint           # builds dist/ if needed, then runs trixie's lintian
make package-test   # make lint, then runs pytest checks on the deb
make e2e            # Playwright suite against a real OMV host
tests/lifecycle.sh root@omv-test.lan dist/openmediavault-garage_0.1.0-1_amd64.deb
```

`make check`, `make unit`, `make lint`, and `make package-test` need no VM.
Each lintian override in `tree/usr/share/lintian/overrides/` carries its
reason.

`make e2e` reads `OMV_HOST`, `OMV_SSH`, `OMV_ADMIN_PASSWORD`, and `OMV_DISK`
from the environment. See `tests/e2e/README.md`. Pass extra test-runner
arguments with `ARGS`, for example `make package-test ARGS=--runxfail`.

`tests/lifecycle.sh` installs the deb on an OMV host over ssh and upgrades it
to a repacked higher version. It then removes, reinstalls, and purges it. It
checks the engine restarts, the instances, files, confdb, ACLs, and the
workbench after each step.

Purge forgets every instance in confdb. The script refuses to run while the
host has instances other than its own throwaway `gt<hex>` ones, unless you
pass `--force`. Instance data is never deleted. The host keeps the tested deb
installed.

## CI

`.github/workflows/build.yml` runs `make check`, `make unit`, and
`make package-test` on every push and pull request, the same commands as
above. Each tool runs in a container pinned in one place. The `Makefile`
pins the PHP, Composer, and actionlint images and nfpm. `ci/tools.Dockerfile`
pins trixie's lintian, shellcheck, yamllint, and dpkg-dev, plus uv. The
workflows pin actions by commit SHA. The e2e suite and `tests/lifecycle.sh`
need the OMV VM and stay local.

## Releasing

Push a tag `v<version>-<release>` that equals the top `debian/changelog`
entry, for example `v0.1.0-1`, or `v0.1.0-2` for a packaging-only fix. CI
fails when the tag and the changelog disagree.

After the checks pass, the `sign` job writes `SHA256SUMS` for the deb and a
detached `SHA256SUMS.asc`. It signs with the key in `GPG_PRIVATE_KEY` and
takes the passphrase from `GPG_PASSPHRASE`, if set. It verifies the signature
against `keys/`. The `publish` job attaches the deb, `SHA256SUMS`, and
`SHA256SUMS.asc` to the GitHub release. Only `sign` sees the secrets, and
only `publish` can write to the repository. Pull requests never reach either
job.

The public key is `keys/release-signing.asc`. The private half lives in the
`release` environment, not in this repository. `make check` fails if private
key material is ever committed.

## Web UI

The vendored binary is
[khairul169/garage-webui](https://github.com/khairul169/garage-webui). The
version and URL are in `build.sh`:

```sh
WEBUI_VERSION=${WEBUI_VERSION:-1.1.0}
.../releases/download/${WEBUI_VERSION}/garage-webui-v${WEBUI_VERSION}-linux-amd64
```

The pin is `checksums/webui-${WEBUI_VERSION}.amd64.sha256`. To update it:

```sh
WEBUI_VERSION=1.2.0 ./build.sh record
```

That downloads the new asset and writes the new checksum. Then change the
default `WEBUI_VERSION` in `build.sh` and in the usage example. Remove the
old checksum if you do not want it. Run `make package-test` and the e2e
suite. The web UI tests cover the proxy, the one-click login, and the
authenticated dashboard. Check
`tree/usr/share/doc/openmediavault-garage/copyright` if the upstream license
or copyright year changed.

A new release may change `BASE_PATH`, `CONFIG_PATH`, `AUTH_USER_PASS`, or the
admin API calls it makes. If it does, the service environment and nginx proxy
may need changes. Test the one-click login and the authenticated dashboard.
A running process is not enough.

## Dependency on garage

The plugin depends on `garage (>= 2.5.0)` because the public endpoint setting
does not exist in 2.4.1. A 2.4.1 user who fills in that field would make
Garage reject the config and the instance would not start. Keep the
dependency in `nfpm.yaml`.

## Repository layout

- `tree/usr/share/openmediavault/datamodels/` - config and RPC schemas
- `tree/usr/share/openmediavault/engined/rpc/garage.inc` - RPC service
- `tree/usr/share/openmediavault/engined/module/garage.inc` - deploy module
- `tree/srv/salt/omv/deploy/garage/` - salt state: toml, secrets, drop-ins,
  ACLs, units, nginx locations, orphan cleanup
- `tree/usr/share/openmediavault/garage/lib/render.php` - the render model:
  every path, data folder, port, ACL, and layout capacity; `render-instances.php`
  prints it for every instance as JSON for the salt state
- `tree/usr/share/openmediavault/garage/lib/live.php` - maps Garage's admin
  API responses to the workbench's bucket, key, and permission rows
- `tree/usr/share/openmediavault/garage/lib/ports.php` - port conflicts,
  shared by create and edit
- `tree/usr/share/openmediavault/garage/lib/owned.php` - what the plugin
  owns: tomls with its marker line and the ACLs it recorded
- `tree/usr/share/openmediavault/garage/lib/drain.php` - when a draining
  datastore is empty; `start-rebalance.sh` restarts the move after a start
  and on every apply
- `tree/usr/share/openmediavault/garage/bootstrap-instance.php` - idempotent
  single-node layout bootstrap
- `tree/var/www/openmediavault/garage-sso/` - one-click web UI sign-in page
  and `auth.php`, the nginx `auth_request` check
- `tree/usr/lib/systemd/system/omv-garage-webui@.service` - web UI template
- `debian/changelog` - package version and history
- `tests/unit/` runs PHPUnit
- `tests/package/` runs pytest on the built deb
- `tests/e2e/` runs Playwright against an OMV host
- `tests/lifecycle.sh` runs the package lifecycle test

## License

GPL-3, copyright bor. The web UI is MIT, copyright Khairul Hidayat. Garage is
AGPL-3, copyright Deuxfleurs and the Garage contributors. The full GPL-3 text
is in [LICENSE](LICENSE). See
`tree/usr/share/doc/openmediavault-garage/copyright` for the per-file
breakdown.
