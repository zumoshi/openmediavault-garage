# garage-tester

Playwright-driven end-to-end tests for the `openmediavault-garage` plugin.
Runs from your machine against a real OMV host over the browser, SSH and
S3. Both `.deb` packages must already be installed on the host; the tests
never install anything.

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

## Run

```bash
uv sync
uv run playwright install chromium   # once
export OMV_HOST=omv-test.lan
export OMV_SSH=root@omv-test.lan
export OMV_ADMIN_PASSWORD='...'
export OMV_DISK=loop                 # substring of the devicefile
uv run pytest -q
```

`OMV_DISK` is matched as a substring against the device files of mounted
filesystems (e.g. `sda` matches `/dev/sda1`, `loop` matches `/dev/loop0`).
