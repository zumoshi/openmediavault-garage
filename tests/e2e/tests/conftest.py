"""Shared fixtures: settings, ssh, rpc, a logged-in page, and factories
for shares and instances with automatic cleanup."""

import secrets

import pytest
from playwright.sync_api import sync_playwright

from garage_tester import instance, ui
from garage_tester.leaks import is_test_name, leftovers
from garage_tester.rpc import NEW_UUID, Rpc
from garage_tester.settings import Settings
from garage_tester.shares import Shares
from garage_tester.ssh import Ssh

@pytest.fixture(scope="session")
def cfg() -> Settings:
    return Settings.from_env()


@pytest.fixture(scope="session")
def ssh(cfg) -> Ssh:
    return Ssh(cfg.ssh_target)


@pytest.fixture(scope="session")
def rpc(ssh) -> Rpc:
    return Rpc(ssh)


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture()
def page(browser, cfg):
    page = browser.new_page()
    ui.login(page, cfg.host, cfg.admin_password)
    yield page
    page.close()


@pytest.fixture(scope="session")
def shares(rpc, ssh, cfg):
    obj = Shares(ssh, rpc, cfg.disk)
    yield obj
    obj.cleanup()


@pytest.fixture()
def make_instance(page, cfg, rpc, ssh, shares):
    """Create an instance through the web UI, apply, and register cleanup.

    Returns (name, info) where info carries the storage share name, the
    meta share name when split, the datastore share name when requested,
    and the instance uuid."""
    created: list[str] = []

    def _make(*, enabled: bool = True, webui: bool = False,
              split: bool = False, ports: dict | None = None,
              extra_datastore: bool = False,
              apply_now: bool = True) -> tuple[str, dict]:
        suffix = secrets.token_hex(3)
        name = f"gt{suffix}"
        storage_share = shares.create(f"gt{suffix}a")
        meta_share = shares.create(f"gt{suffix}b") if split else None
        ds_share = shares.create(f"gt{suffix}c") if extra_datastore else None
        ui.goto_instances(page, cfg.host)
        ui.create_instance(
            page, name, storage_share, enabled=enabled, webui=webui,
            split_meta_share=meta_share, ports=ports)
        created.append(name)
        if apply_now:
            ui.apply_via_ui(page)
        if enabled:
            ssh.wait_unit_running(f"garage@{name}")
        if extra_datastore:
            uuid = rpc.instance_uuid(name)
            rpc.call("Garage", "setDatastore", {
                "uuid": NEW_UUID, "instanceuuid": uuid,
                "shareuuid": shares.uuid_by_name(ds_share), "capacity": 5})
            rpc.apply(["garage"])
        return name, {"storage_share": storage_share,
                      "meta_share": meta_share,
                      "datastore_share": ds_share,
                      "uuid": rpc.instance_uuid(name)}

    yield _make

    for name in created:
        try:
            rpc.delete_instance(name)
        except Exception:
            pass
    if created:
        rpc.apply(["garage"])


@pytest.fixture()
def s3_setup(cfg, rpc, ssh):
    """Wire bucket + key + mapping for an instance and return the s3
    connection details."""
    def _make(name: str, uuid: str):
        key_id, secret = instance.setup_bucket_and_key(
            rpc, uuid, f"gt-{name}", f"gt-{name}-key")
        row = instance.instance_row(rpc, name)
        instance.wait_health(ssh, row["adminport"])
        return {"endpoint": f"http://{cfg.host}:{row['s3port']}",
                "key_id": key_id, "secret": secret,
                "bucket": f"gt-{name}"}
    yield _make


@pytest.fixture(scope="session", autouse=True)
def cleanup_stale(cfg, ssh, rpc):
    """Remove instances and shared folders a crashed earlier run left
    behind. Builds its own Shares rather than using the `shares` fixture,
    which must be torn down before no_leaks checks the box."""
    stale = [i["name"] for i in rpc.enumerate_instances()
             if is_test_name(i["name"])]
    for name in stale:
        rpc.delete_instance(name)
    if stale:
        rpc.apply(["garage"])
    shares = Shares(ssh, rpc, cfg.disk)
    shares.delete([n for n in shares.names() if is_test_name(n)])


@pytest.fixture()
def fresh_page(browser):
    """A browser page with no OMV session (no cookies)."""
    page = browser.new_page()
    yield page
    page.close()


@pytest.fixture(scope="session", autouse=True)
def no_leaks(ssh, cleanup_stale):
    """Fail the run if anything the suite creates is left on the box.
    Autouse and session scoped, so it is set up before and torn down after
    every other fixture that creates state."""
    if found := leftovers(ssh):
        pytest.fail("box not clean after cleanup_stale:\n  "
                    + "\n  ".join(found), pytrace=False)
    yield
    if found := leftovers(ssh):
        pytest.fail("the suite leaked:\n  " + "\n  ".join(found),
                    pytrace=False)
