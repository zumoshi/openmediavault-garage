"""Shared folder setup on the disk given via OMV_DISK."""

import json
import shlex

from .rpc import Rpc
from .ssh import Ssh

NEW_UUID = "fa4b1c66-ef79-11e5-87a0-0002b3a176b4"


class Shares:
    def __init__(self, ssh: Ssh, rpc: Rpc, disk: str):
        self.ssh = ssh
        self.rpc = rpc
        self.disk = disk
        self._created: list[str] = []

    def _mount(self) -> dict:
        mounts = json.loads(self.ssh.out(
            "omv-confdbadm read conf.system.filesystem.mountpoint"))
        for m in mounts:
            device = self.ssh.out(f"findmnt -n -o SOURCE {shlex.quote(m['dir'])}")
            if self.disk in device or self.disk in m.get("fsname", ""):
                return m
        raise RuntimeError(
            f"no mounted filesystem matching disk {self.disk!r}")

    def create(self, name: str) -> str:
        """Create shared folder `name` and apply. Returns its name."""
        m = self._mount()
        self.rpc.call("ShareMgmt", "set", {
            "uuid": NEW_UUID,
            "name": name,
            "reldirpath": f"{name}/",
            "comment": "garage tester",
            "mntentref": m["uuid"],
            "mode": "775",
        })
        self.rpc.apply(["sharedfolders"])
        self._created.append(name)
        return name

    def cleanup(self):
        for name in self._created:
            share_uuid = self.uuid_by_name(name)
            self.rpc.call("ShareMgmt", "delete",
                          {"uuid": share_uuid, "recursive": True})
        if self._created:
            self.rpc.apply(["sharedfolders"])
        self._created.clear()

    def uuid_by_name(self, name: str) -> str:
        shares = json.loads(self.ssh.out(
            "omv-confdbadm read conf.system.sharedfolder"))
        return next(s["uuid"] for s in shares if s["name"] == name)

