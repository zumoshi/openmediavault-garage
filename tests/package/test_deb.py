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


def test_architecture_is_amd64(deb: Path) -> None:
    assert run("dpkg-deb", "-f", deb, "Architecture") == "amd64"


def test_ships_no_dev_files(deb: Path) -> None:
    tar = subprocess.run(["dpkg-deb", "--fsys-tarfile", deb], check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as members:
        paths = [m.name.removeprefix("./") for m in members]
    assert any(p.startswith("usr/share/openmediavault/") for p in paths)
    dev_files = [p for p in paths if DEV_FILE.search(p)]
    assert not dev_files, "dev files in the deb:\n" + "\n".join(dev_files)


def test_version_matches_changelog(deb: Path) -> None:
    changelog = run("dpkg-parsechangelog", "-l", REPO / "debian/changelog", "-S", "Version")
    assert run("dpkg-deb", "-f", deb, "Version") == changelog
