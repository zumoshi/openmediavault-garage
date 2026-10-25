"""Rejection paths. Every test here asserts that access is DENIED or that
a degraded state is visible, from outside the OMV session."""

import http.cookiejar
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
from garage_tester.ssh import shquote


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


def _get(url: str, cookie: str | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"Cookie": cookie} if cookie else {})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


def _webui_cookie(ssh, uuid: str) -> str:
    """Sign in to the web UI on loopback, the way only the box itself can,
    and return its session cookie."""
    row = next(i for i in ssh.confdb("conf.service.garage.instance")
               if i["uuid"] == uuid)
    login = json.dumps({"username": row["webuiuser"],
                        "password": row["webuipassword"]})
    jar = ssh.out(
        "curl -s -o /dev/null -c - -H 'Content-Type: application/json' "
        f"-d {shquote(login)} "
        f"http://127.0.0.1:{row['webuiport']}/garage-webui-{row['name']}"
        "/api/auth/login")
    cookies = [line.split("\t") for line in jar.splitlines()
               if line.count("\t") == 6]
    assert cookies, f"web UI login on loopback set no cookie: {jar}"
    return "; ".join(f"{c[5]}={c[6]}" for c in cookies)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "REVIEW 2.10: nginx proxies /garage-webui-<name>/ to anyone who can "
    "reach OMV; the web UI's own login is the only gate"))
def test_webui_requires_omv_session(cfg, webui_instance):
    name, _ = webui_instance
    url = f"http://{cfg.host}/garage-webui-{name}/"
    status, body = _get(url)
    assert status in (401, 403), \
        f"GET {url} without an OMV session got {status}: {body[:200]}"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "REVIEW 2.10: the web UI API holds the admin token and nginx serves it "
    "to anyone with a web UI cookie, OMV session or not"))
def test_webui_api_requires_omv_session(cfg, ssh, webui_instance):
    """Every /api/ path already answers 401 to a caller with no cookie at
    all, from the web UI itself, so that alone proves nothing. A caller
    holding the web UI's own session but no OMV session must be turned
    away too."""
    name, info = webui_instance
    url = f"http://{cfg.host}/garage-webui-{name}/api/buckets"
    status, body = _get(url, cookie=_webui_cookie(ssh, info["uuid"]))
    assert status in (401, 403), (
        f"GET {url} with a web UI cookie but no OMV session got {status}: "
        f"{body[:200]}")


@pytest.fixture(scope="module")
def non_admin_cookie(cfg, rpc):
    """The session cookie of a throwaway OMV user without the administrator
    role, signed in through rpc.php like the workbench does."""
    name, password = f"gt{secrets.token_hex(3)}", secrets.token_hex(12)
    rpc.call("UserMgmt", "setUser", {
        "name": name, "groups": ["users"], "password": password,
        "email": "", "disallowusermod": False, "sshpubkeys": []})
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(
        f"http://{cfg.host}/rpc.php",
        data=json.dumps({"service": "Session", "method": "login",
                         "params": {"username": name,
                                    "password": password}}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with opener.open(req, timeout=15) as r:
        login = json.load(r)
    assert (login["response"] or {}).get("status") == "authenticated", \
        f"non-admin OMV login failed: {login}"
    yield "; ".join(f"{c.name}={c.value}" for c in jar)
    rpc.call("UserMgmt", "deleteUser", {"name": name})


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "REVIEW 2.10: nginx proxies /garage-webui-<name>/ to any caller, so an "
    "OMV session without the administrator role reaches the web UI too"))
@pytest.mark.parametrize("path", ["", "api/buckets"])
def test_webui_rejects_non_admin_omv_session(cfg, webui_instance,
                                             non_admin_cookie, path):
    name, _ = webui_instance
    url = f"http://{cfg.host}/garage-webui-{name}/{path}"
    status, body = _get(url, cookie=non_admin_cookie)
    assert status == 403, \
        f"GET {url} with a non-admin OMV session got {status}: {body[:200]}"


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
