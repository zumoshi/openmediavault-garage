"""Loop filesystems registered in OMV, for tests that need a filesystem of
a given size. A test filesystem is named gt<hex> like everything else the
suite owns: its image is /root/<name>.img and its OMV mount point carries
the name as its comment."""

from .rpc import Rpc
from .ssh import Ssh, shquote


def image(name: str) -> str:
    return f"/root/{name}.img"


def create(ssh: Ssh, rpc: Rpc, name: str, size: str) -> str:
    """Make an ext4 image of `size` (truncate syntax), attach it, and mount
    it through OMV. Returns the uuid of its mount point."""
    img = shquote(image(name))
    device = ssh.out(f"truncate -s {size} {img} && mkfs.ext4 -q -F {img} "
                     f"&& losetup -f --show {img}")
    mount = rpc.call("FileSystemMgmt", "setMountPoint",
                     {"id": device, "comment": name})
    rpc.apply(["fstab"])
    return mount["uuid"]


def remove(ssh: Ssh, rpc: Rpc, name: str) -> None:
    """Unmount and unregister filesystem `name`, detach and delete its
    image. Whatever part of it exists."""
    for m in ssh.confdb("conf.system.filesystem.mountpoint"):
        if m["comment"] == name:
            rpc.call("FileSystemMgmt", "umountByDir", {"dir": m["dir"]})
    img = shquote(image(name))
    ssh.run(f"losetup -n -O NAME -j {img} | xargs -r -n1 losetup -d; "
            f"rm -f {img}")


def names(ssh: Ssh) -> set[str]:
    """The name of every mount point comment, image in /root and loop
    device backed by one. Filter with leaks.is_test_name."""
    found = {m["comment"]
             for m in ssh.confdb("conf.system.filesystem.mountpoint")}
    images = ssh.out("find /root -maxdepth 1 -name '*.img'").split()
    images += [line.split(maxsplit=1)[1] for line in
               ssh.out("losetup -n -O NAME,BACK-FILE").splitlines()]
    return found | {f.removeprefix("/root/").removesuffix(".img")
                    for f in images if f.startswith("/root/")}
