"""Rejection paths. Every test here asserts that access is DENIED or that
a degraded state is visible, from outside the OMV session."""

import json
import re
import secrets
import urllib.error
import urllib.request

import pytest
from botocore.exceptions import ClientError
from playwright.sync_api import expect

from garage_tester import instance, s3, ui
from garage_tester.rpc import NEW_UUID


@pytest.fixture(scope="module")
def webui_instance(browser, cfg, rpc, ssh, shares):
    """One webui-enabled instance shared by the security tests, created
    through the web UI and deleted afterwards."""
    page = browser.new_page()
    ui.login(page, cfg.host, cfg.admin_password)
    suffix = secrets.token_hex(3)
    name = f"gt{suffix}"
    share = shares.create(f"gt{suffix}a")
    ui.goto_instances(page, cfg.host)
    ui.create_instance(page, name, share, webui=True)
    ui.apply_via_ui(page)
    ssh.wait_unit_running(f"garage@{name}")
    uuid = rpc.instance_uuid(name)
    yield name, {"storage_share": share, "uuid": uuid}
    rpc.delete_instance(name)
    rpc.apply(["garage"])
    page.close()


def _post_rpc(cfg, service, method, params):
    req = urllib.request.Request(
        f"http://{cfg.host}/rpc.php",
        data=json.dumps({"service": service, "method": method,
                         "params": params}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_sso_without_omv_session_rejected(fresh_page, cfg, webui_instance):
    """The SSO page without an OMV session must fail to sign in and must
    never land in an authenticated web UI."""
    name, _ = webui_instance
    fresh_page.goto(f"http://{cfg.host}/garage-sso/?instance={name}")
    expect(fresh_page.locator("body")).to_contain_text(
        re.compile("error", re.I), timeout=15000)
    assert f"/garage-webui-{name}/" not in fresh_page.url, \
        "SSO page reached the web UI without an OMV session"


def test_webui_direct_access_shows_own_login(fresh_page, cfg, webui_instance):
    """Direct webui access without an OMV session (and without the webui
    session cookie) must show the web UI's own login form."""
    name, _ = webui_instance
    fresh_page.goto(f"http://{cfg.host}/garage-webui-{name}/")
    expect(fresh_page.locator("input[type=password]").first).to_be_visible(
        timeout=15000)
    body = fresh_page.locator("body").inner_text().lower()
    assert "healthy" not in body, \
        f"unauthenticated visitor sees a live dashboard: {body[:200]}"


def _assert_session_rejected(status: int, body: str) -> None:
    """OMV's rpc.php must turn the call away before it reaches the plugin.
    A crash inside the plugin would also be non-200, so assert the session
    error itself."""
    error = json.loads(body).get("error") or {}
    assert (status, error.get("message")) == \
        (401, "Session not authenticated."), \
        f"expected OMV's session error, got {status}: {body[:300]}"


def test_getwebuilogin_rpc_requires_session(cfg, webui_instance):
    """Garage.getWebUiLogin hands out the web UI password, so it must not
    answer an unauthenticated caller."""
    name, _ = webui_instance
    _assert_session_rejected(
        *_post_rpc(cfg, "Garage", "getWebUiLogin", {"name": name}))


def test_unauthenticated_write_rpc_rejected(cfg):
    _assert_session_rejected(
        *_post_rpc(cfg, "Garage", "setInstance", {"uuid": "x", "name": "nope"}))


def test_omv_wrong_password_rejected(fresh_page, cfg):
    fresh_page.goto(f"http://{cfg.host}/", wait_until="networkidle")
    fresh_page.get_by_role("textbox", name="User name").fill("admin")
    fresh_page.get_by_role("textbox", name="Password").fill("wrong-password")
    fresh_page.get_by_role("button", name="Log in").click()
    expect(fresh_page.get_by_text("Incorrect username or password.")
           ).to_be_visible(timeout=15000)
    assert "login" in fresh_page.url, \
        f"wrong password reached the workbench: {fresh_page.url}"


def test_s3_invalid_key_denied(cfg, rpc, make_instance):
    name, _ = make_instance()
    port = instance.instance_row(rpc, name)["s3port"]
    s3.must_be_denied(f"http://{cfg.host}:{port}")


def test_s3_unmapped_key_denied(cfg, rpc, make_instance):
    name, info = make_instance()
    s3_port = instance.instance_row(rpc, name)["s3port"]
    bucket = f"gt-{secrets.token_hex(3)}"
    rpc.call("Garage", "setBucket", {
        "uuid": NEW_UUID, "instanceuuid": info["uuid"], "name": bucket,
        "maxsize": 0, "maxobjects": 0, "website": False,
        "indexdoc": "index.html", "errordoc": ""})
    stray = rpc.call("Garage", "setKey", {
        "uuid": NEW_UUID, "instanceuuid": info["uuid"],
        "name": "gt-stray-key", "keyid": "", "secret": ""})
    s3c = s3.client(f"http://{cfg.host}:{s3_port}",
                    stray["keyid"], stray["secret"])
    try:
        s3c.put_object(Bucket=bucket, Key="nope", Body=b"x")
    except ClientError:
        return
    raise AssertionError("unmapped S3 key was allowed to write")


def test_admin_and_webui_ports_not_reachable_from_lan(cfg, rpc,
                                                      make_instance):
    name, info = make_instance(webui=True)
    row = instance.instance_row(rpc, name)
    for label, port in (("admin", row["adminport"]),
                        ("webui", row["webuiport"])):
        try:
            urllib.request.urlopen(f"http://{cfg.host}:{port}/", timeout=5)
        except (urllib.error.URLError, OSError):
            continue
        raise AssertionError(f"{label} port {port} is reachable from the LAN")
