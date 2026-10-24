"""OMV RPC access, tunnelled over ssh as root via omv-rpc. This is the
same engine the workbench talks to; the browser tests cover the UI path."""

import json

from .ssh import Ssh, shquote


# OMV's placeholder uuid that tells a set RPC to create a new object.
NEW_UUID = "fa4b1c66-ef79-11e5-87a0-0002b3a176b4"


class RpcError(Exception):
    pass


class Rpc:
    def __init__(self, ssh: Ssh):
        self.ssh = ssh

    def call(self, service: str, method: str, params: dict | None = None):
        payload = json.dumps(params or {})
        rc, out = self.ssh.run(
            f"omv-rpc -u admin {shquote(service)} {shquote(method)} "
            f"{shquote(payload)}", check=False)
        try:
            data = json.loads(out.strip())
        except json.JSONDecodeError:
            raise AssertionError(f"{service}.{method}: bad output: {out[:300]}")
        if isinstance(data, dict) and data.get("error"):
            raise RpcError(f"{service}.{method}: "
                           f"{data['error'].get('message', 'unknown')}")
        return data

    def apply(self, modules: list[str] | None = None):
        rc, out = self.ssh.run(
            "omv-rpc -u admin config applyChanges "
            f"'{{\"modules\": {json.dumps(modules or [])}, \"force\": true}}'",
            check=False)
        if "Result: False" in out or '"error"' in out:
            raise AssertionError(f"apply failed: {out[-600:]}")

    def enumerate_instances(self) -> list[dict]:
        return self.call("Garage", "enumerateInstances")

    def instance_uuid(self, name: str) -> str:
        matches = [i for i in self.enumerate_instances() if i["name"] == name]
        if not matches:
            raise AssertionError(f"instance {name} not found")
        return matches[0]["uuid"]

    def delete_instance(self, name: str):
        self.call("Garage", "deleteInstance",
                  {"uuid": self.instance_uuid(name)})
