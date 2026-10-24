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
  - N buckets with quotas and optional S3 website hosting
  - N access keys (created or imported)
  - a key-to-bucket permission mapping (read/write/owner)
- Always-on listeners: S3 API (all interfaces) and internal RPC (loopback)
- Checkboxes for the optional listeners: admin API (loopback) and website
  hosting (all interfaces)
- Unused ports are pre-suggested when creating an instance; duplicate ports
  on create are silently resolved to the next free port
- Optional vendored community web UI (khairul169/garage-webui, MIT), disabled
  by default, reachable only through the authenticated OMV web interface with
  one-click sign-in (no password prompt, credentials never leave the server
  side of OMV)

## Install

```sh
apt install ./openmediavault-garage_0.1.0-1_all.deb
```

Requires the `garage` package (see the `garage-debian` repo). Then find the
plugin under **Services > Garage**.

Workflow per instance:

1. Create an instance: name, ports, metadata shared folder.
2. Add datastores (shared folders + capacity).
3. Apply the pending configuration changes (top bar checkmark). The salt
   deploy renders `/etc/garage/<name>.toml`, the systemd drop-in, ACLs, and
   starts `garage@<name>`, then bootstraps the single-node layout with the
   aggregated datastore capacity.
4. Create buckets, keys and access mappings (requires the instance running).
5. Point S3 clients at `http://<omv>:<s3port>` with the region and a key.

## Security model

- Garage and the web UI run as the system user `garage` (no shell), with
  `ProtectSystem=strict`, `NoNewPrivileges`, system-call filtering, and
  per-instance `ReadWritePaths` limited to the chosen shared folders.
- Configs and secrets live in `/etc/garage/` (0600/0640, `root:garage`).
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
./build.sh    # dist/openmediavault-garage_0.1.0-1_all.deb
```

The package version comes from the top entry of `debian/changelog`.
Needs `nfpm` and `curl`. The vendored webui binary is checksum-pinned in
`checksums/` and verified at build time; CI enforces it.

## Layout

- `tree/usr/share/openmediavault/datamodels/` - config + RPC schemas
- `tree/usr/share/openmediavault/engined/rpc/garage.inc` - RPC service
- `tree/usr/share/openmediavault/engined/module/garage.inc` - deploy module
- `tree/srv/salt/omv/deploy/garage/` - salt state: toml, secrets, drop-ins,
  ACLs, units, nginx locations, orphan cleanup
- `tree/usr/share/openmediavault/garage/bootstrap-instance.php` - idempotent
  single-node layout bootstrap (wait, assign, apply, converge capacity)
- `tree/usr/share/openmediavault/garage/sso/` (installed to
  `/var/www/openmediavault/garage-sso/`) - one-click web UI sign-in page
- `tree/usr/lib/systemd/system/omv-garage-webui@.service` - web UI template
- `debian/changelog` - package version and history, shipped as
  `changelog.Debian.gz`

## License

GPL-3, copyright bor. The vendored web UI is MIT, copyright Khairul Hidayat.
Garage is AGPL-3, copyright Deuxfleurs and the Garage contributors. See
`tree/usr/share/doc/openmediavault-garage/copyright`.
