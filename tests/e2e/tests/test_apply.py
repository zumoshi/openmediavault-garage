"""What a garage apply may touch: only the instances OMV manages, and
each of them on its own."""

import re
import secrets

import pytest

from garage_tester import ui
from garage_tester.ssh import shquote

HANDMADE_TOML = """\
metadata_dir = "/var/lib/garage/{name}/meta"
data_dir = "/var/lib/garage/{name}/data"
db_engine = "lmdb"
replication_factor = 1
rpc_bind_addr = "127.0.0.1:3991"
rpc_secret_file = "/etc/garage/{name}.rpc_secret"

[s3_api]
s3_region = "garage"
api_bind_addr = "127.0.0.1:3990"
"""

HANDMADE_DROP_IN = """\
[Service]
Environment=RUST_LOG=garage=debug
"""


@pytest.fixture()
def handmade_instance(ssh):
    """A garage instance configured by hand, as the garage-debian README
    describes: a toml and a unit drop-in, never started. Its name does not
    look like the suite's, so it stands for the admin's own instance."""
    name = f"handmade{secrets.token_hex(3)}"
    files = {f"/etc/garage/{name}.toml": HANDMADE_TOML.format(name=name),
             f"/etc/systemd/system/garage@{name}.service.d/override.conf":
                 HANDMADE_DROP_IN}
    try:
        for path, content in files.items():
            ssh.run(f"mkdir -p $(dirname {path}) && cat > {path} <<'EOF'\n"
                    f"{content}EOF")
        yield files
    finally:
        ssh.run(f"rm -rf /etc/garage/{name}.toml "
                f"/etc/systemd/system/garage@{name}.service.d && "
                "systemctl daemon-reload")


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "REVIEW 1.4: apply purges every /etc/garage/*.toml that is not in "
    "confdb, and its unit drop-in"))
def test_apply_keeps_handmade_instance(ssh, rpc, handmade_instance):
    rpc.apply(["garage"])
    kept = {path: ssh.file_exists(path) and ssh.read_file(path) == content
            for path, content in handmade_instance.items()}
    assert all(kept.values()), \
        f"a garage apply removed or changed hand-written files: {kept}"


@pytest.fixture()
def make_broken_instance(ssh, shares, make_instance):
    """Make an instance whose Salt states fail on every apply: its storage
    directory is moved away behind OMV's back, as if it was deleted on
    disk. The directory is moved back before the instance is removed."""
    moved: list[str] = []

    def _make() -> str:
        name, info = make_instance()
        path = shares.path(info["storage_share"])
        ssh.run(f"mv {shquote(path)} {shquote(path + '.gone')}")
        moved.append(path)
        return name

    yield _make

    for path in moved:
        ssh.run(f"mv {shquote(path + '.gone')} {shquote(path)}")


def test_broken_instance_does_not_block_apply(page, cfg, ssh, rpc,
                                              make_instance,
                                              make_broken_instance):
    healthy, info = make_instance()
    broken = make_broken_instance()
    params = rpc.call("Garage", "getInstance", {"uuid": info["uuid"]})
    rpc.call("Garage", "setInstance", {**params, "loglevel": "debug"})

    ui.goto_instances(page, cfg.host)
    with pytest.raises(AssertionError) as apply_error:
        ui.apply_via_ui(page, timeout_s=600)
    failed = re.findall(r"ID: (\S+)", str(apply_error.value))
    assert failed and all(s.endswith(f"_{broken}") for s in failed), \
        f"the apply must fail in the states of {broken} only: {apply_error.value}"

    ssh.wait_unit_running(f"garage@{healthy}")
    pid = ssh.unit_state(f"garage@{healthy}")["MainPID"]
    env = ssh.out(f"tr '\\0' '\\n' < /proc/{pid}/environ")
    assert "RUST_LOG=garage=debug" in env.splitlines(), \
        f"garage@{healthy} does not run with the new log level: {env}"
