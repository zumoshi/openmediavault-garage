"""Variations: web UI on/off, split vs single storage, custom ports,
extra datastores, disabled instances, and deletion cleanup."""

import re

import pytest
from playwright.sync_api import expect

from garage_tester import instance, s3, ui


def test_webui_enabled_and_sso(page, cfg, ssh, rpc, make_instance):
    name, info = make_instance(webui=True)

    assert ssh.file_exists(f"/etc/garage/{name}.webui.env"), \
        "webui env file missing"
    env = ssh.read_file(f"/etc/garage/{name}.webui.env")
    assert "AUTH_USER_PASS=admin:$2" in env, "webui password hash missing"
    assert ssh.file_exists(
        f"/etc/nginx/openmediavault-webgui.d/garage-webui-{name}.conf")
    assert ssh.unit_active(f"omv-garage-webui@{name}")

    ui.goto_instances(page, cfg.host)
    popup = ui.open_webui(page, name)
    popup.wait_for_url(lambda url: f"/garage-webui-{name}/" in url)
    expect(popup.locator("body")).to_contain_text(
        re.compile("healthy", re.I), timeout=15000)
    body = popup.locator("body").inner_text().lower()
    assert "dashboard" in body and "healthy" in body, \
        f"web UI did not load an authenticated dashboard: {body[:200]}"
    popup.close()


def test_webui_disabled_by_default(ssh, make_instance):
    name, info = make_instance(webui=False)
    assert not ssh.file_exists(f"/etc/garage/{name}.webui.env")
    assert not ssh.file_exists(
        f"/etc/nginx/openmediavault-webgui.d/garage-webui-{name}.conf")
    assert not ssh.unit_active(f"omv-garage-webui@{name}")


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "REVIEW 2.7: with a separate metadata folder and no datastore, the "
    "template renders data_dir without a capacity and garage never starts"))
def test_split_storage(page, cfg, ssh, shares, make_instance, s3_setup):
    name, info = make_instance(split=True, extra_datastore=True)
    toml = instance.read_instance_toml(ssh, name)
    metapath = shares.path(info["meta_share"])
    ds_path = shares.path(info["datastore_share"])
    assert toml["metadata_dir"] == f"{metapath}/meta", toml["metadata_dir"]
    assert len(toml["data_dir"]) == 1, toml["data_dir"]
    assert toml["data_dir"][0]["path"].rstrip("/") == ds_path

    conn = s3_setup(name, info["uuid"])
    s3.round_trip(conn["endpoint"], conn["key_id"],
                  conn["secret"], conn["bucket"], b"split storage works")


def test_custom_ports(page, cfg, ssh, make_instance, s3_setup):
    ports = {"S3 API port": 23900, "RPC port": 23901,
             "Admin API port": 23903}
    name, info = make_instance(ports=ports)
    toml = instance.read_instance_toml(ssh, name)
    assert toml["s3_api"]["api_bind_addr"] == "[::]:23900"
    assert toml["rpc_bind_addr"] == "127.0.0.1:23901"
    assert toml["admin"]["api_bind_addr"] == "127.0.0.1:23903"
    assert ssh.run("ss -tln | grep -q ':23900 '", check=False)[0] == 0, \
        "S3 port not listening"
    assert ssh.run("ss -tln | grep -q ':23903 '", check=False)[0] == 0, \
        "admin port not listening"

    conn = s3_setup(name, info["uuid"])
    s3.round_trip(conn["endpoint"], conn["key_id"], conn["secret"],
                  conn["bucket"], b"custom ports work")


def test_extra_datastore(page, cfg, ssh, shares, make_instance, s3_setup):
    name, info = make_instance(extra_datastore=True)
    ds_share = info.get("datastore_share")
    assert ds_share, "fixture did not provide a datastore share"
    toml = instance.read_instance_toml(ssh, name)
    ds_path = shares.path(ds_share)
    paths = [d["path"].rstrip("/") for d in toml["data_dir"]]
    assert ds_path in paths, (ds_path, paths)

    conn = s3_setup(name, info["uuid"])
    s3.round_trip(conn["endpoint"], conn["key_id"],
                  conn["secret"], conn["bucket"], b"extra datastore works")


def test_disabled_instance(page, cfg, ssh, make_instance):
    name, info = make_instance(enabled=False)
    assert not ssh.unit_active(f"garage@{name}")
    assert not ssh.file_exists(f"/etc/garage/{name}.toml")
    assert not ssh.file_exists(f"/etc/garage/{name}.rpc_secret")


def test_delete_cleanup(page, cfg, ssh, shares, make_instance):
    name, info = make_instance(webui=True)
    storpath = shares.path(info["storage_share"])
    assert ssh.run(f"getfacl -p {storpath} | grep -q user:garage",
                   check=False)[0] == 0, "storage ACL not granted"

    ui.goto_instances(page, cfg.host)
    ui.delete_instance_via_ui(page, name)
    ui.apply_via_ui(page)

    assert not ssh.file_exists(f"/etc/garage/{name}.toml"), "toml not purged"
    assert not ssh.file_exists(f"/etc/garage/{name}.webui.env"), "env purged"
    assert not ssh.unit_active(f"garage@{name}")
    assert not ssh.unit_active(f"omv-garage-webui@{name}")
    assert not ssh.file_exists(
        f"/etc/nginx/openmediavault-webgui.d/garage-webui-{name}.conf")
    assert ssh.run(f"getfacl -p {storpath} | grep -q user:garage",
                   check=False)[0] != 0, "storage ACL was not revoked"
