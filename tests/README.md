# tests

End-to-end tests for the plugin. They run as root on a real OMV host and
exercise the installed package through the same RPCs and HTTP endpoints
the workbench uses. Nothing is mocked.

## Run

```bash
sudo python3 tests/e2e.py
```

Options via environment:

| Variable    | Default          | Meaning                                   |
|-------------|------------------|-------------------------------------------|
| `E2E_SHARE` | `garage-data3`   | Shared folder used as scratch storage     |
| `E2E_BASE`  | `127.0.0.1`      | Base URL for the web UI login request     |
| `E2E_SKIP_S3` | unset          | Set to `1` to skip the awscli round trip  |

The lifecycle test creates an instance, deploys it, exercises
bucket/key/permission calls plus an S3 upload and download, then deletes
everything and asserts the cleanup (config files, systemd unit, nginx
location, ACLs).

## Requirements on the host

- The plugin package installed
- `awscli` (only for the S3 round trip; skip with `E2E_SKIP_S3=1`)
- A shared folder that garage can be pointed at, not used by another
  instance
