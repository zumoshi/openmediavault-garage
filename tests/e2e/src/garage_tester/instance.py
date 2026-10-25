"""Bucket, key and permission setup plus config-file assertions."""

import json
import tomllib
import time

from .rpc import Rpc
from .ssh import shquote


def setup_bucket_and_key(rpc: Rpc, instance_uuid: str,
                         bucket: str, key_name: str) -> tuple[str, str]:
    """Create bucket, key and an owner permission. Returns (key_id, secret)."""
    bucket_id = rpc.call("Garage", "setBucket", {
        "instanceuuid": instance_uuid, "id": "", "name": bucket,
        "maxsize": 0, "maxobjects": 0, "website": False,
        "indexdoc": "index.html", "errordoc": ""})["id"]
    key = rpc.call("Garage", "setKey", {
        "instanceuuid": instance_uuid, "id": "", "name": key_name})
    rpc.call("Garage", "setMapping", {
        "instanceuuid": instance_uuid, "keyid": key["id"],
        "bucketid": bucket_id,
        "allowread": True, "allowwrite": True, "allowowner": True})
    return key["id"], key["secret"]


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


def instance_row(rpc: Rpc, name: str) -> dict:
    listing = rpc.call("Garage", "getInstanceList",
                       {"start": 0, "limit": -1})
    return next(x for x in listing["data"] if x["name"] == name)


def garage_json(ssh, name: str, endpoint: str, payload: dict | None = None):
    """Call garage's admin API directly, the way the garage web UI does,
    bypassing OMV."""
    payload_part = f" {shquote(json.dumps(payload))}" if payload else ""
    return json.loads(ssh.out(
        f"/usr/bin/garage -c /etc/garage/{name}.toml json-api "
        f"{endpoint}{payload_part}"))


def garage_acl(ssh, path: str) -> bool:
    """Whether `path` grants the garage user an ACL entry."""
    return ssh.run(f"getfacl -p {shquote(path)} | grep -q user:garage",
                   check=False)[0] == 0
