"""Shared folder setup on the disk given via OMV_DISK."""

import shlex

from .rpc import NEW_UUID, Rpc
from .ssh import Ssh


class Shares:
    def __init__(self, ssh: Ssh, rpc: Rpc, disk: str):
        self.ssh = ssh
        self.rpc = rpc
        self.disk = disk
        self._created: list[str] = []

    def _mount(self) -> dict:
        for m in self.ssh.confdb("conf.system.filesystem.mountpoint"):
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
        self.delete(self._created)
        self._created.clear()

    def delete(self, names: list[str]):
        """Delete shared folders `names` with their content, and apply."""
        for name in names:
            self.rpc.call("ShareMgmt", "delete",
                          {"uuid": self.uuid_by_name(name), "recursive": True})
        if names:
            self.rpc.apply(["sharedfolders"])

    def names(self) -> list[str]:
        return [s["name"] for s in self.ssh.confdb("conf.system.sharedfolder")]

    def _row(self, name: str) -> dict:
        return next(s for s in self.ssh.confdb("conf.system.sharedfolder")
                    if s["name"] == name)

    def uuid_by_name(self, name: str) -> str:
        return self._row(name)["uuid"]

    def path(self, name: str) -> str:
        """Absolute path of shared folder `name`, without a trailing slash."""
        share = self._row(name)
        mount = next(m for m in self.ssh.confdb("conf.system.filesystem.mountpoint")
                     if m["uuid"] == share["mntentref"])
        return mount["dir"].rstrip("/") + "/" + share["reldirpath"].strip("/")

