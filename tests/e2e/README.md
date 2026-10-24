# End-to-end tests

Playwright-driven end-to-end tests for the `openmediavault-garage` plugin,
in `tests/e2e/` of this repository. They run from your machine against a
real OMV host over the browser, SSH and S3. The `garage` and
`openmediavault-garage` packages must already be installed on the host.
The tests never install anything.

## What is covered

- Headless browser login, instance creation through the real form, apply
  through the pending-changes banner, and an S3 round trip via boto3.
- Web UI toggle on and off (unit, nginx location, environment file).
- Single storage versus separate metadata folder.
- Custom S3/RPC/admin ports (generated config plus listening sockets).
- Extra datastores (two-entry `data_dir`).
- Disabled instances.
- Instance deletion through the UI with cleanup assertions, including
  ACL revocation on the storage folder.

Every advanced test validates the generated `/etc/garage/<name>.toml`
over SSH and then talks to the running instance.

## Requirements

- Python 3.12 with [uv](https://docs.astral.sh/uv/)
- The OMV host reachable over HTTP and SSH (key auth for root)
- The shares used by the tests are created and removed by the suite on
  the disk you point it at

## What the suite owns on the host

Every instance and shared folder the suite creates is named `gt` followed
by 6 hex digits, sometimes with a suffix letter (`gt1a2b3c`, `gt1a2b3ca`).
Do not give your own instances or shares names of that form. The suite
deletes them.

Two session fixtures in `tests/conftest.py` keep the host clean:

- `cleanup_stale` deletes `gt<hex>` instances and shared folders that an
  interrupted run left behind.
- `no_leaks` checks the host before the first test and after the last
  teardown. It fails the run if a `gt<hex>` instance, shared folder,
  `/etc/garage` file, nginx location, `garage@` unit drop-in, or
  `garage@`/`omv-garage-webui@` unit that is not inactive is left, and
  lists each one.

## Run

Run these commands from `tests/e2e/`:

```bash
uv sync
uv run playwright install chromium   # once
export OMV_HOST=omv-test.lan
export OMV_SSH=root@omv-test.lan
export OMV_ADMIN_PASSWORD='...'
export OMV_DISK=loop                 # substring of the devicefile
uv run pytest -q
```

A full run takes about 15 minutes.

`OMV_DISK` is matched as a substring against the device files of mounted
filesystems (e.g. `sda` matches `/dev/sda1`, `loop` matches `/dev/loop0`).
