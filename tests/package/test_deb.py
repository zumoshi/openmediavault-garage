import io
import re
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

DEV_FILE = re.compile(
    r"(^|/)(tests|vendor)(/|$)"
    r"|(^|/)(composer\.(json|lock)|phpunit\.xml(\.dist)?|\.phpunit\.cache)(/|$)"
    r"|\.py$"
)


def run(*args: str | Path) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(scope="module")
def deb() -> Path:
    debs = list((REPO / "dist").glob("*.deb"))
    assert len(debs) == 1, f"expected exactly one deb in dist/, found {debs}; run make package-test"
    return debs[0]


def files(deb: Path) -> dict[str, bytes]:
    tar = subprocess.run(["dpkg-deb", "--fsys-tarfile", deb], check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as members:
        return {m.name.removeprefix("./"): members.extractfile(m).read() if m.isfile() else b""
                for m in members}


def test_architecture_is_amd64(deb: Path) -> None:
    assert run("dpkg-deb", "-f", deb, "Architecture") == "amd64"


def test_ships_no_dev_files(deb: Path) -> None:
    paths = list(files(deb))
    assert any(p.startswith("usr/share/openmediavault/") for p in paths)
    dev_files = [p for p in paths if DEV_FILE.search(p)]
    assert not dev_files, "dev files in the deb:\n" + "\n".join(dev_files)


def test_version_matches_changelog(deb: Path) -> None:
    changelog = run("dpkg-parsechangelog", "-l", REPO / "debian/changelog", "-S", "Version")
    assert run("dpkg-deb", "-f", deb, "Version") == changelog


def test_salt_writes_values_through_literal(deb: Path) -> None:
    raw = [f"{path}:{n}" for path, content in files(deb).items()
           if path.startswith("srv/salt/omv/deploy/garage/")
           and not path.endswith("/literal.jinja")
           for n, line in enumerate(content.decode().splitlines(), 1)
           if re.search(r"\|\s*json\b", line)]
    assert not raw, "use literal(), the json filter leaves DEL, C1, U+2028 and U+2029 raw:\n" + "\n".join(raw)
