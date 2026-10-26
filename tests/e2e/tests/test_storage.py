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


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "REVIEW 1.2: deleteDatastore drops the data_dir entry without moving "
    "its blocks, so the objects stored there become unreadable"))
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


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "REVIEW 2.10: removing a datastore leaves u:garage in its shared "
    "folder's ACL"))
def test_datastore_removal_revokes_acl(ssh, rpc, shares, make_instance):
    name, info = make_instance(extra_datastore=True)
    ds_path = shares.path(info["datastore_share"])
    assert instance.garage_acl(ssh, ds_path), "datastore ACL not granted"

    _remove_datastore(rpc, info["uuid"],
                      lambda: ssh.wait_unit_running(f"garage@{name}"))
    assert not instance.garage_acl(ssh, ds_path), \
        f"{ds_path} still grants u:garage after its datastore was removed"


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


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "REVIEW 2.7: the storage capacity is 90% of free space floored to GiB, "
    "so below 1.1 GiB free it renders no capacity and garage never starts"))
def test_storage_on_small_filesystem(share_on_filesystem, make_instance,
                                     s3_setup):
    """A 1 GiB filesystem has less free space than the 1.1 GiB the storage
    folder's capacity needed."""
    name, info = make_instance(storage_share=share_on_filesystem("1G"))
    conn = s3_setup(name, info["uuid"])
    s3.round_trip(conn["endpoint"], conn["key_id"], conn["secret"],
                  conn["bucket"], b"small filesystem works")


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "REVIEW 2.7: the storage capacity follows free space, so an apply after "
    "the disk filled up rewrites the toml, restarts garage and bumps the "
    "layout"))
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
