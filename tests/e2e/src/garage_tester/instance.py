"""Bucket, key and permission setup plus config-file assertions."""

import tomllib
import time

from .rpc import Rpc

NEW_UUID = "fa4b1c66-ef79-11e5-87a0-0002b3a176b4"


def setup_bucket_and_key(rpc: Rpc, instance_uuid: str,
                         bucket: str, key_name: str) -> tuple[str, str]:
    """Create bucket, key and an owner mapping. Returns (key_id, secret)."""
    rpc.call("Garage", "setBucket", {
        "uuid": NEW_UUID, "instanceuuid": instance_uuid, "name": bucket,
        "maxsize": 0, "maxobjects": 0, "website": False,
        "indexdoc": "index.html", "errordoc": ""})
    key = rpc.call("Garage", "setKey", {
        "uuid": NEW_UUID, "instanceuuid": instance_uuid,
        "name": key_name, "keyid": "", "secret": ""})

    def find_uuid(method: str, row_name: str) -> str:
        listing = rpc.call("Garage", method, {"start": 0, "limit": -1,
                                    "instanceuuid": instance_uuid})
        for row in listing["data"]:
            if row["name"] == row_name:
                return row["uuid"]
        raise AssertionError(f"{method}: row {row_name!r} not found")

    rpc.call("Garage", "setMapping", {
        "uuid": NEW_UUID, "instanceuuid": instance_uuid,
        "keyuuid": find_uuid("getKeyList", key_name),
        "bucketuuid": find_uuid("getBucketList", bucket),
        "allowread": True, "allowwrite": True, "allowowner": True})
    return key["keyid"], key["secret"]


def read_instance_toml(ssh, name: str) -> dict:
    return tomllib.loads(ssh.read_file(f"/etc/garage/{name}.toml"))


def wait_health(ssh, admin_port: int, timeout_s: int = 120) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        rc, out = ssh.run(
            f"curl -s -o /dev/null -w '%{{http_code}}' "
            f"http://127.0.0.1:{admin_port}/health", check=False)
        if rc == 0 and out.strip() == "200":
            return
        time.sleep(3)
    raise AssertionError(f"admin health on {admin_port} never returned 200")


def instance_ports(rpc: Rpc, name: str) -> dict:
    listing = rpc.call("Garage", "getInstanceList",
                       {"start": 0, "limit": -1})
    row = next(i for i in listing["data"] if i["name"] == name)
    return {"s3": row["s3port"], "rpc": row["rpcport"],
            "admin": row["adminport"]}


def instance_ports(rpc: Rpc, name: str) -> dict:
    listing = rpc.call("Garage", "getInstanceList",
                       {"start": 0, "limit": -1})
    row = next(i for i in listing["data"] if i["name"] == name)
    return {"s3": row["s3port"], "rpc": row["rpcport"],
            "admin": row["adminport"]}


def share_path(ssh, share_name: str) -> str:
    import json
    shares = json.loads(ssh.out(
        "omv-confdbadm read conf.system.sharedfolder"))
    share = next(s for s in shares if s["name"] == share_name)
    mounts = json.loads(ssh.out(
        "omv-confdbadm read conf.system.filesystem.mountpoint"))
    mp = next(m for m in mounts if m["uuid"] == share["mntentref"])
    return mp["dir"].rstrip("/") + "/" + share["reldirpath"].strip("/")
