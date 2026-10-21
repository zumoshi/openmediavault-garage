"""Shared fixtures: settings, ssh, rpc, a logged-in page, and factories
for shares and instances with automatic cleanup."""

import secrets

import pytest
from playwright.sync_api import sync_playwright

from garage_tester import instance, ui
from garage_tester.rpc import Rpc
from garage_tester.settings import Settings
from garage_tester.ssh import Ssh

NEW_UUID = "fa4b1c66-ef79-11e5-87a0-0002b3a176b4"


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
    from garage_tester.shares import Shares
    obj = Shares(ssh, rpc, cfg.disk)
    yield obj
    obj.cleanup()


@pytest.fixture(scope="session")
def make_share(shares):
    created = []

    def _make(base: str) -> str:
        name = f"gt-{base}-{secrets.token_hex(3)}"
        shares.create(name)
        created.append(name)
        return name

    yield _make
    for name in created:
        uuid = shares.uuid_by_name(name)
        rpc.call("ShareMgmt", "delete", {"uuid": uuid, "recursive": True})
    if created:
        rpc.apply(["sharedfolders"])


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
            ui.wait_unit_running(ssh, name)
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
    def _make(name: str, uuid: str, s3_port: int):
        key_id, secret = instance.setup_bucket_and_key(
            rpc, uuid, f"gt-{name}", f"gt-{name}-key")
        admin_port = instance.instance_ports(rpc, name)["admin"]
        instance.wait_health(ssh, admin_port)
        return {"endpoint": f"http://{cfg.host}:{s3_port}",
                "key_id": key_id, "secret": secret,
                "bucket": f"gt-{name}"}
    yield _make


@pytest.fixture(scope="session", autouse=True)
def cleanup_stale(rpc):
    """Remove gt-* instances a crashed earlier run may have left behind."""
    for i in rpc.enumerate_instances():
        if i["name"].startswith("gt-"):
            rpc.delete_instance(i["uuid"])
    rpc.apply(["garage"])
    yield
