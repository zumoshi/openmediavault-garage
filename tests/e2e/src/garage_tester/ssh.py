"""SSH access to the OMV host. Delegates to the local ssh binary so
~/.ssh/config, agents and jump hosts all keep working."""

import json
import subprocess


class Ssh:
    def __init__(self, target: str):
        self.target = target

    def run(self, cmd: str, check: bool = True) -> tuple[int, str]:
        p = subprocess.run(["ssh", self.target, cmd],
                           capture_output=True, text=True, timeout=120)
        if check and p.returncode != 0:
            raise RuntimeError(f"ssh command failed ({p.returncode}): {cmd}\n"
                               f"{p.stdout[-400:]}\n{p.stderr[-400:]}")
        return p.returncode, (p.stdout + p.stderr)

    def out(self, cmd: str) -> str:
        return self.run(cmd)[1].strip()

    def confdb(self, key: str):
        return json.loads(self.out(f"omv-confdbadm read {shquote(key)}"))

    def read_file(self, path: str) -> str:
        rc, out = self.run(f"cat {shquote(path)}", check=False)
        if rc != 0:
            raise FileNotFoundError(f"{path} on {self.target}")
        return out

    def file_exists(self, path: str) -> bool:
        return self.run(f"test -e {shquote(path)}", check=False)[0] == 0

    def unit_active(self, unit: str) -> bool:
        return self.run(f"systemctl is-active {shquote(unit)}",
                        check=False)[1].strip() == "active"

    def port_listening(self, port: int) -> bool:
        rc, _ = self.run(f"ss -tln | grep -q ':{port} '", check=False)
        return rc == 0


def shquote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"
