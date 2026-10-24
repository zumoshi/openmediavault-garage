"""Rejection paths. Every test here asserts that access is DENIED or that
a degraded state is visible, from outside the OMV session."""

import json
import secrets
import urllib.error
import urllib.request

import pytest
from botocore.exceptions import ClientError

from garage_tester import instance, s3, ui
from garage_tester.instance import instance_ports

NEW_UUID = "fa4b1c66-ef79-11e5-87a0-0002b3a176b4"


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
    ui.wait_unit_running(ssh, name)
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
    fresh_page.wait_for_timeout(6000)
    assert f"/garage-webui-{name}/" not in fresh_page.url, \
        "SSO page reached the web UI without an OMV session"
    body = fresh_page.locator("body").inner_text().lower()
    assert "error" in body, \
        f"expected a visible sign-in error, got: {body[:200]}"


def test_webui_direct_access_shows_own_login(fresh_page, cfg, webui_instance):
    """Direct webui access without an OMV session (and without the webui
    session cookie) must show the web UI's own login form."""
    name, _ = webui_instance
    fresh_page.goto(f"http://{cfg.host}/garage-webui-{name}/")
    fresh_page.wait_for_timeout(3000)
    body = fresh_page.locator("body").inner_text().lower()
    assert "healthy" not in body, \
        f"unauthenticated visitor sees a live dashboard: {body[:200]}"
    assert fresh_page.locator(
        "input[type=password]").count() > 0, \
        "web UI login form not shown to unauthenticated visitor"


def test_getwebuilogin_rpc_requires_session(cfg, webui_instance):
    """Garage.getWebUiLogin must not hand out credentials to an
    unauthenticated caller."""
    name, _ = webui_instance
    status, body = _post_rpc(cfg, "Garage", "getWebUiLogin", {"name": name})
    compact = body.replace(" ", "")
    leaked = '"password":"' in compact and '"password":""' not in compact
    assert status != 200 or not leaked, \
        f"getWebUiLogin leaked credentials without a session ({status}): {body[:200]}"


def test_unauthenticated_write_rpc_rejected(cfg):
    status, _ = _post_rpc(cfg, "Garage", "setInstance",
                          {"uuid": "x", "name": "nope"})
    assert status != 200, f"unauthenticated write accepted ({status})"


def test_omv_wrong_password_rejected(fresh_page, cfg):
    fresh_page.goto(f"http://{cfg.host}/", wait_until="networkidle")
    fresh_page.get_by_role("textbox", name="User name").fill("admin")
    fresh_page.get_by_role("textbox", name="Password").fill("wrong-password")
    fresh_page.get_by_role("button", name="Log in").click()
    fresh_page.wait_for_timeout(2500)
    assert "login" in fresh_page.url, \
        f"wrong password reached the workbench: {fresh_page.url}"


def test_s3_invalid_key_denied(cfg, rpc, make_instance):
    name, _ = make_instance()
    port = instance.instance_ports(rpc, name)["s3"]
    s3.must_be_denied(f"http://{cfg.host}:{port}")


def test_s3_unmapped_key_denied(cfg, rpc, make_instance):
    name, info = make_instance()
    s3_port = instance.instance_ports(rpc, name)["s3"]
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
    ports = instance.instance_ports(rpc, name)
    webui_port = instance.instance_row(rpc, name)["webuiport"]
    for label, port in (("admin", ports["admin"]), ("webui", webui_port)):
        try:
            urllib.request.urlopen(f"http://{cfg.host}:{port}/", timeout=5)
        except (urllib.error.URLError, OSError):
            continue
        raise AssertionError(f"{label} port {port} is reachable from the LAN")
