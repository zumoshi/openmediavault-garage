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
  ACL revocation on the storage folder, and undoing a pending delete.
- Editing an instance through the real edit form: a no-op edit, a
  read-only name, and rejected renames, port conflicts and region values.
- A storage shared folder whose path contains a space, and a storage
  shared folder on a filesystem with less than 1.1 GiB free.
- Removing a datastore keeps every object readable and revokes the
  datastore's ACL.
- The web UI is reachable only with an OMV session.
- Buckets, access keys and permissions created, edited and deleted
  through the details page, checked against garage.
- Keys, buckets and permissions made or deleted directly against garage
  show up once in the lists, also when the details page loads its tabs at
  the same time. A bucket without a global alias is listed by its id with
  its usage. Key secrets come only from the key's own page. The same bucket
  and key names on two instances.
- A stopped instance's bucket, key and permission calls fail at once and
  say so.
- The confdb migration from the version that mirrored garage's state.
- An apply leaves hand-written garage instances alone, and one instance
  that fails to deploy does not stop the others from applying.

## Open bugs

A test for a known, unfixed bug is marked
`@pytest.mark.xfail(strict=True, raises=AssertionError, reason="REVIEW <id>: ...")`,
naming its finding in the review. The suite stays green while the bug is
open. A fix makes the test pass, and strict mode turns that XPASS into a
failure until the fix also removes the marker. Run
`uv run pytest --runxfail` to see what each open bug's test reports.

Every advanced test validates the generated `/etc/garage/<name>.toml`
over SSH and then talks to the running instance.

## Requirements

- Python 3.12 with [uv](https://docs.astral.sh/uv/)
- The OMV host reachable over HTTP and SSH (key auth for root)
- The shares used by the tests are created and removed by the suite on
  the disk you point it at

## What the suite owns on the host

Every instance, shared folder and loop filesystem the suite creates is
named `gt` followed by 6 hex digits, sometimes with a suffix letter
(`gt1a2b3c`, `gt1a2b3ca`). Do not give your own instances, shares or
filesystems names of that form. The suite deletes them.

A loop filesystem `<name>` is the image `/root/<name>.img`, attached to a
loop device and mounted through OMV with `<name>` as the mount point's
comment.

Two session fixtures in `tests/conftest.py` keep the host clean:

- `cleanup_stale` deletes `gt<hex>` instances, shared folders and loop
  filesystems that an interrupted run left behind.
- `no_leaks` checks the host before the first test and after the last
  teardown. It fails the run if a `gt<hex>` instance, shared folder,
  `/etc/garage` file, nginx location, `garage@` unit drop-in,
  `garage@`/`omv-garage-webui@` unit that is not inactive, or any part of
  a loop filesystem is left, and lists each one.

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

A full run takes about 29 minutes.

`OMV_DISK` is matched as a substring against the device files of mounted
filesystems (e.g. `sda` matches `/dev/sda1`, `loop` matches `/dev/loop0`).
