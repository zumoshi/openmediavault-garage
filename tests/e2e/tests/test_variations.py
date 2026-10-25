"""Variations: web UI on/off, split vs single storage, custom ports,
extra datastores, disabled instances, a share path with a space, and
deletion cleanup and undo."""

import json
import re
import secrets

import pytest
from playwright.sync_api import expect

from garage_tester import instance, s3, ui
from garage_tester.ssh import shquote


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


def _webui_login_status(ssh, row: dict, password: str) -> str:
    """HTTP status of a web UI sign-in on loopback with `password`."""
    login = json.dumps({"username": row["webuiuser"], "password": password})
    return ssh.out(
        "curl -s -o /dev/null -w '%{http_code}' "
        f"-H 'Content-Type: application/json' -d {shquote(login)} "
        f"http://127.0.0.1:{row['webuiport']}/garage-webui-{row['name']}"
        "/api/auth/login")


def test_webui_password_is_the_only_stored_secret(ssh, rpc, make_instance):
    """confdb keeps the web UI password and no hash of it. Re-applying
    leaves the web UI alone; a renewed password signs in and the old one
    no longer does."""
    name, info = make_instance(webui=True)
    unit = f"omv-garage-webui@{name}"
    env_file = f"/etc/garage/{name}.webui.env"
    row = next(i for i in ssh.confdb("conf.service.garage.instance")
               if i["uuid"] == info["uuid"])
    assert "webuipasswordhash" not in row, "confdb stores a password hash"

    env, pid = ssh.read_file(env_file), ssh.unit_state(unit)["MainPID"]
    rpc.apply(["garage"])
    assert (ssh.read_file(env_file), ssh.unit_state(unit)["MainPID"]) == \
        (env, pid), "an apply without changes rewrote the env or restarted"

    old = row["webuipassword"]
    new = rpc.call("Garage", "renewWebUiPassword",
                   {"uuid": info["uuid"]})["password"]
    rpc.apply(["garage"])
    ssh.wait_unit_running(unit)
    assert (_webui_login_status(ssh, row, new),
            _webui_login_status(ssh, row, old)) == ("200", "401"), \
        "sign-in status with the (renewed, old) password"


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
    assert instance.garage_acl(ssh, storpath), "storage ACL not granted"

    ui.goto_instances(page, cfg.host)
    ui.delete_instance_via_ui(page, name)
    ui.apply_via_ui(page)

    assert not ssh.file_exists(f"/etc/garage/{name}.toml"), "toml not purged"
    assert not ssh.file_exists(f"/etc/garage/{name}.webui.env"), "env purged"
    assert not ssh.unit_active(f"garage@{name}")
    assert not ssh.unit_active(f"omv-garage-webui@{name}")
    assert not ssh.file_exists(
        f"/etc/nginx/openmediavault-webgui.d/garage-webui-{name}.conf")
    assert not instance.garage_acl(ssh, storpath), \
        "storage ACL was not revoked"


def test_share_path_with_space(ssh, shares, make_instance, s3_setup):
    share = f"gt{secrets.token_hex(3)}"
    shares.create(share, reldirpath=f"{share} with space/")
    name, info = make_instance(storage_share=share)
    toml = instance.read_instance_toml(ssh, name)
    assert toml["metadata_dir"] == f"{shares.path(share)}/meta", \
        toml["metadata_dir"]

    conn = s3_setup(name, info["uuid"])
    s3.round_trip(conn["endpoint"], conn["key_id"], conn["secret"],
                  conn["bucket"], b"share path with a space works")


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "REVIEW 2.6: deleteInstance stops the units and removes the files at "
    "once, so undoing the pending delete leaves a dead instance"))
def test_undo_delete_keeps_instance_running(page, cfg, ssh, make_instance):
    name, info = make_instance()
    ui.goto_instances(page, cfg.host)
    ui.delete_instance_via_ui(page, name)
    ui.undo_via_ui(page)

    names = [i["name"] for i in ssh.confdb("conf.service.garage.instance")]
    assert name in names, f"undo did not bring {name} back: {names}"
    toml = ssh.file_exists(f"/etc/garage/{name}.toml")
    state = ssh.unit_state(f"garage@{name}")
    assert toml and state["SubState"] == "running", (
        f"after undoing its delete, {name} is back in confdb but "
        f"garage@{name} is {state['ActiveState']}/{state['SubState']} and "
        f"its toml is {'present' if toml else 'gone'}")
