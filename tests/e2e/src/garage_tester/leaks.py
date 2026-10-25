"""What the suite owns on the box. Every instance, shared folder,
filesystem and user it creates is named gt<6 hex>, optionally followed by a suffix
letter."""

import re

from . import filesystems

TEST_NAME = re.compile(r"gt[0-9a-f]{6}")


def is_test_name(name: str) -> bool:
    return TEST_NAME.match(name) is not None


# Directories the plugin writes per-instance files into, with the file
# name prefix that comes before the instance name.
INSTANCE_FILES = (
    ("/etc/garage", ""),
    ("/etc/nginx/openmediavault-webgui.d", "garage-webui-"),
    ("/etc/systemd/system", "garage@"),
)


def users(ssh) -> list[str]:
    """The suite's OMV user accounts."""
    return [u for u in ssh.out("getent passwd | cut -d: -f1").split()
            if is_test_name(u)]


def leftovers(ssh) -> list[str]:
    """Everything of the suite's that is still on the box."""
    found = [f"instance {i['name']}"
             for i in ssh.confdb("conf.service.garage.instance")
             if is_test_name(i["name"])]
    found += [f"shared folder {s['name']}"
              for s in ssh.confdb("conf.system.sharedfolder")
              if is_test_name(s["name"])]
    for directory, prefix in INSTANCE_FILES:
        found += [f"{directory}/{f}"
                  for f in ssh.out(f"ls -1 {directory}").split()
                  if f.startswith(prefix) and is_test_name(f[len(prefix):])]
    units = ssh.out("systemctl list-units --all --plain --no-legend "
                    "'garage@*' 'omv-garage-webui@*'")
    for line in units.splitlines():
        unit, _load, active, sub = line.split()[:4]
        if active != "inactive" and is_test_name(unit.split("@", 1)[1]):
            found.append(f"unit {unit} ({active}/{sub})")
    found += [f"user {name}" for name in users(ssh)]
    found += [f"filesystem {name}" for name in sorted(filesystems.names(ssh))
              if is_test_name(name)]
    return found
