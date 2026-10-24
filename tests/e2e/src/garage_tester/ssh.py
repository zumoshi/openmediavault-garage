"""SSH access to the OMV host. Delegates to the local ssh binary so
~/.ssh/config, agents and jump hosts all keep working."""

import json
import subprocess
import time
from contextlib import contextmanager


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

    def unit_state(self, unit: str) -> dict[str, str]:
        out = self.out("systemctl show -p ActiveState,SubState,MainPID,NRestarts "
                       f"{shquote(unit)}")
        return dict(line.split("=", 1) for line in out.splitlines())

    def wait_unit_running(self, unit: str, timeout_s: int = 240) -> None:
        """Wait until `unit` runs and stays up. A crash-looping unit is
        briefly active on every attempt, so the same process must still be
        running, with no restart in between, a full RestartSec (5s) later."""
        deadline = time.time() + timeout_s
        state = self.unit_state(unit)
        while time.time() < deadline:
            if state["SubState"] == "running":
                time.sleep(6)
                later = self.unit_state(unit)
                if later == state:
                    return
                state = later
            else:
                time.sleep(3)
                state = self.unit_state(unit)
        raise AssertionError(f"{unit} never stayed running, last seen {state}")

    def port_listening(self, port: int) -> bool:
        rc, _ = self.run(f"ss -tln | grep -q ':{port} '", check=False)
        return rc == 0

    @contextmanager
    def listener(self, port: int):
        """A process outside garage listening on 127.0.0.1:`port`."""
        pid = self.out(
            "setsid python3 -c 'import socket, time; s = socket.socket(); "
            f's.bind(("127.0.0.1", {port})); s.listen(); time.sleep(3600)\' '
            "</dev/null >/dev/null 2>&1 & echo $!")
        try:
            for _ in range(20):
                if self.port_listening(port):
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError(f"listener on {port} never came up")
            yield port
        finally:
            self.run(f"kill {pid}", check=False)


def shquote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"
