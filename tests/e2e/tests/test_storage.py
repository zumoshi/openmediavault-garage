"""Where an instance keeps its data: removing a datastore, and a storage
folder on a small or filling filesystem."""

import secrets
import time

import pytest

from garage_tester import filesystems, instance, s3
from garage_tester.rpc import RpcError
from garage_tester.ssh import shquote

OBJECTS = 80
OBJECT_SIZE = 64 * 1024


def _datastore_uuids(rpc, instance_uuid: str) -> list[str]:
    listing = rpc.call("Garage", "getDatastoreList",
                       {"start": 0, "limit": -1, "instanceuuid": instance_uuid})
    return [d["uuid"] for d in listing["data"]]


def _block_files(ssh, path: str) -> int:
    return int(ssh.out(
        f"find {path} -type f ! -name garage-marker | wc -l"))


def _remove_datastore(rpc, instance_uuid: str, check,
                      timeout_s: int = 300) -> None:
    """Remove the instance's one datastore the way the Datastores tab does:
    Delete, then apply. Removal may drain the datastore first, so delete
    and apply again until the row is gone. Runs `check` after every
    apply."""
    [uuid] = _datastore_uuids(rpc, instance_uuid)
    deadline = time.time() + timeout_s
    while True:
        try:
            rpc.call("Garage", "deleteDatastore", {"uuid": uuid})
        except RpcError:
            pass  # still draining
        rpc.apply(["garage"])
        check()
        if uuid not in _datastore_uuids(rpc, instance_uuid):
            return
        assert time.time() < deadline, \
            f"datastore {uuid} still listed {timeout_s}s after its delete"
        time.sleep(10)


def test_datastore_removal_keeps_objects(ssh, rpc, shares, make_instance,
                                         s3_setup):
    name, info = make_instance(extra_datastore=True)
    conn = s3_setup(name, info["uuid"])
    client = s3.client(conn["endpoint"], conn["key_id"], conn["secret"])
    digests = s3.put_random_objects(client, conn["bucket"], OBJECTS,
                                    OBJECT_SIZE)
    ds_path = shares.path(info["datastore_share"])
    on_datastore = _block_files(ssh, ds_path)
    assert on_datastore > 0, f"no block of {OBJECTS} objects is on {ds_path}"
    admin_port = instance.instance_row(rpc, name)["adminport"]

    def all_readable() -> None:
        ssh.wait_unit_running(f"garage@{name}")
        instance.wait_health(ssh, admin_port)
        failed = s3.unreadable(client, conn["bucket"], digests)
        assert not failed, (
            f"{len(failed)} of {OBJECTS} objects unreadable after removing "
            f"the datastore that held {on_datastore} block files, e.g. "
            f"{next(iter(failed.items()))}")

    _remove_datastore(rpc, info["uuid"], all_readable)
    all_readable()


def test_datastore_removal_revokes_acl(ssh, rpc, shares, make_instance):
    name, info = make_instance(extra_datastore=True)
    ds_path = shares.path(info["datastore_share"])
    assert instance.garage_acl(ssh, ds_path), "datastore ACL not granted"

    _remove_datastore(rpc, info["uuid"],
                      lambda: ssh.wait_unit_running(f"garage@{name}"))
    assert not instance.garage_acl(ssh, ds_path), \
        f"{ds_path} still grants u:garage after its datastore was removed"
    left = ssh.out(f"find {shquote(ds_path)} -mindepth 1")
    assert not left, f"garage left this in the removed datastore: {left}"


def _rebalances(ssh, name: str) -> list[dict]:
    workers = instance.garage_json(ssh, name, "ListWorkers", {
        "node": "self", "body": {"busyOnly": False}})["success"]
    return [w for node in workers.values() for w in node
            if w["name"] == "Block rebalance worker"]


def test_datastore_drain_resumes_after_a_garage_restart(
        ssh, rpc, shares, make_instance, s3_setup):
    """The rebalance that drains a datastore lives in garage's memory. A
    restart that is not an apply, like a reboot, must start it again."""
    name, info = make_instance(extra_datastore=True)
    conn = s3_setup(name, info["uuid"])
    client = s3.client(conn["endpoint"], conn["key_id"], conn["secret"])
    digests = s3.put_random_objects(client, conn["bucket"], 30, OBJECT_SIZE)
    ds_path = shares.path(info["datastore_share"])
    on_datastore = _block_files(ssh, ds_path)
    assert on_datastore > 0, f"no block of 30 objects is on {ds_path}"
    [uuid] = _datastore_uuids(rpc, info["uuid"])
    unit = f"garage@{name}"

    # Garage cannot write below the storage folder's data directory, so
    # the rebalance started by the apply moves nothing and gives up. The
    # apply resets the mode of the data directory itself, not of the hash
    # directories in it.
    data_dir = shquote(shares.path(info["storage_share"]) + "/data")
    ssh.out(f"cd {data_dir} && for i in $(seq 0 255); do "
            "d=$(printf %02x $i); mkdir -p $d; chown garage:garage $d; "
            "done && find . -mindepth 1 -type d -exec chmod u-w {} +")
    try:
        rpc.call("Garage", "deleteDatastore", {"uuid": uuid})
        rpc.apply(["garage"])
        ssh.wait_unit_running(unit)
        assert uuid in _datastore_uuids(rpc, info["uuid"]), \
            "the datastore row went before its data was moved"
        deadline = time.time() + 180
        while not any(w["state"] == "done" for w in _rebalances(ssh, name)):
            assert time.time() < deadline, \
                f"rebalance not done after 180s: {_rebalances(ssh, name)}"
            time.sleep(3)
        assert _block_files(ssh, ds_path) == on_datastore, \
            "blocks moved although the storage folder was not writable"
    finally:
        ssh.out(f"find {data_dir} -mindepth 1 -type d -exec chmod u+w {{}} +")

    ssh.out(f"systemctl restart {unit}")
    ssh.wait_unit_running(unit)
    deadline = time.time() + 180
    while True:
        try:
            rpc.call("Garage", "deleteDatastore", {"uuid": uuid})
            break
        except RpcError as e:
            assert time.time() < deadline, (
                f"datastore not removable 180s after the restart: {e}; "
                f"{_block_files(ssh, ds_path)} block files left")
            time.sleep(5)
    rpc.apply(["garage"])
    ssh.wait_unit_running(unit)
    assert uuid not in _datastore_uuids(rpc, info["uuid"])
    assert ds_path not in ssh.read_file(f"/etc/garage/{name}.toml"), \
        "the removed datastore is still a data_dir"
    failed = s3.unreadable(client, conn["bucket"], digests)
    assert not failed, f"{len(failed)} of 30 objects unreadable: {failed}"


def test_datastore_edit_keeps_its_shared_folder(rpc, shares, make_instance):
    name, info = make_instance(extra_datastore=True)
    [uuid] = _datastore_uuids(rpc, info["uuid"])
    row = rpc.call("Garage", "getDatastore", {"uuid": uuid})
    other = shares.uuid_by_name(shares.create(f"{name}d"))

    try:
        rpc.call("Garage", "setDatastore", {**row, "shareuuid": other})
    except RpcError:
        pass
    after = rpc.call("Garage", "getDatastore", {"uuid": uuid})
    assert after["shareuuid"] == row["shareuuid"], \
        "the datastore moved to another shared folder"

    rpc.call("Garage", "setDatastore", {**row, "capacity": 7})
    after = rpc.call("Garage", "getDatastore", {"uuid": uuid})
    assert (after["shareuuid"], after["capacity"]) == (row["shareuuid"], 7)


@pytest.fixture()
def share_on_filesystem(ssh, rpc, shares):
    """Make a shared folder on its own filesystem of `size` (truncate
    syntax). Returns its name."""
    made: list[str] = []

    def _make(size: str) -> str:
        name = f"gt{secrets.token_hex(3)}"
        made.append(name)
        mount = filesystems.create(ssh, rpc, name, size)
        return shares.create(name, mntentref=mount)

    yield _make
    for name in made:
        if name in shares.names():
            shares.delete([name])
        filesystems.remove(ssh, rpc, name)


def test_storage_on_small_filesystem(share_on_filesystem, make_instance,
                                     s3_setup):
    """A 1 GiB filesystem has less free space than the 1.1 GiB the storage
    folder's capacity needed."""
    name, info = make_instance(storage_share=share_on_filesystem("1G"))
    conn = s3_setup(name, info["uuid"])
    s3.round_trip(conn["endpoint"], conn["key_id"], conn["secret"],
                  conn["bucket"], b"small filesystem works")


def test_filling_the_disk_changes_nothing_on_apply(ssh, rpc, shares,
                                                   share_on_filesystem,
                                                   make_instance):
    share = share_on_filesystem("4G")
    name, info = make_instance(storage_share=share)
    unit = f"garage@{name}"

    def pid_and_layout() -> tuple[int, int]:
        return (ssh.unit_state(unit)["MainPID"],
                instance.garage_json(ssh, name, "GetClusterLayout")["version"])

    before = pid_and_layout()
    ssh.out(f"fallocate -l 2G {shquote(shares.path(share) + '/filler')}")
    rpc.apply(["garage"])
    ssh.wait_unit_running(unit)
    assert pid_and_layout() == before, \
        "(garage PID, layout version) before and after filling the disk"
