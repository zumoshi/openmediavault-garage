#!/usr/bin/env python3
"""End-to-end tests for openmediavault-garage.

Run as root on the OMV host under test:

    sudo python3 tests/e2e.py

Environment overrides:
    E2E_SHARE      shared folder name used as scratch storage (default garage-data3)
    E2E_BASE       OMV base URL (default http://127.0.0.1)
    E2E_SKIP_S3    set to 1 to skip the awscli round trip

Exit code 0 means every test passed.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("E2E_BASE", "http://127.0.0.1")
SHARE_NAME = os.environ.get("E2E_SHARE", "garage-data3")
SKIP_S3 = os.environ.get("E2E_SKIP_S3") == "1"
GARAGE = "/usr/bin/garage"
NEW_UUID = "fa4b1c66-ef79-11e5-87a0-0002b3a176b4"
ETC = "/etc/garage"
NGINXD = "/etc/nginx/openmediavault-webgui.d"
TREE = "/usr/share/openmediavault"

RESULTS = []


def run(cmd, check=True, input=None):
    p = subprocess.run(cmd, capture_output=True, text=True, input=input)
    if check and p.returncode != 0:
        raise AssertionError(f"command failed: {' '.join(cmd)}\n{p.stderr[:400]}")
    return p


def rpc(service, method, params=None):
    p = run(["omv-rpc", "-u", "admin", service, method,
             json.dumps(params or {})], check=False)
    payload = p.stdout.strip() or p.stderr.strip()
    try:
        out = json.loads(payload)
    except json.JSONDecodeError:
        raise AssertionError(
            f"{service}.{method}: unparseable output: {payload[:200]}")
    if isinstance(out, dict) and out.get("error"):
        raise RpcError(out["error"].get("message", "rpc error"))
    return out


class RpcError(Exception):
    pass


def sh(cmd, check=True):
    return run(["bash", "-c", cmd], check=check).stdout.strip()


def shq(s):
    return "'" + s.replace("'", "'\\''") + "'"


def check(name, fn):
    try:
        fn()
        RESULTS.append((name, True, ""))
        print(f"PASS {name}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((name, False, str(e)))
        print(f"FAIL {name}: {e}")


def free_port_set():
    ports = rpc("Garage", "suggestPorts")
    return ports


def make_instance_params(name, share_uuid, enable=True, split=False,
                         meta_uuid="", s3port=None, rpcport=None,
                         adminport=None, webport=None, webuiport=None,
                         webui=False, ds_share_uuid=None):
    p = free_port_set()
    return {
        "uuid": NEW_UUID,
        "enable": enable,
        "name": name,
        "storageshareuuid": share_uuid,
        "storagesplit": split,
        "metadatashareuuid": meta_uuid,
        "snapshotsshareuuid": "",
        "snapshotinterval": "",
        "s3port": s3port or p["s3port"],
        "rpcport": rpcport or p["rpcport"],
        "webport": webport or p["webport"],
        "adminport": adminport or p["adminport"],
        "webuiport": webuiport or p["webuiport"],
        "s3region": "garage",
        "s3rootdomain": "",
        "webenable": False,
        "webrootdomain": "",
        "adminenable": True,
        "dbengine": "lmdb",
        "compressionlevel": 1,
        "compressiondisable": False,
        "metadatafsync": False,
        "datafsync": False,
        "disablescrub": False,
        "loglevel": "info",
        "blocksize": "",
        "blockrambuffermax": "",
        "blockmaxconcurrentreads": 16,
        "blockmaxconcurrentwrites": 3,
        "lmdbmapsize": "",
        "webuienable": webui,
        "webuiuser": "admin",
        "webuipassword": "",
    }


def apply_changes():
    p = run(["omv-rpc", "-u", "admin", "config", "applyChanges",
             json.dumps({"modules": ["garage"], "force": True})], check=False)
    try:
        out = json.loads(p.stdout)
    except json.JSONDecodeError:
        raise AssertionError(f"apply unparseable: {p.stdout[:200]} {p.stderr[:200]}")
    if isinstance(out, dict) and out.get("error"):
        msg = out["error"].get("message", "")
        i = msg.find("Result: False")
        raise AssertionError("apply failed: "
                             + (msg[max(0, i - 400):i + 200] if i >= 0 else msg[:600]))


def wait_active(unit, seconds=15):
    for _ in range(seconds):
        if sh(f"systemctl is-active {unit} 2>/dev/null") == "active":
            return
        time.sleep(1)
    raise AssertionError(f"{unit} not active after {seconds}s")


def share_uuid_by_name(name):
    shares = json.loads(sh(
        "omv-confdbadm read conf.system.sharedfolder"))
    return next(s["uuid"] for s in shares if s["name"] == name)


def instance_uuid(name):
    insts = rpc("Garage", "enumerateInstances")
    return next(i["uuid"] for i in insts if i["name"] == name)


# ---------------------------------------------------------------- static

def test_datamodels():
    inst = json.load(open(f"{TREE}/datamodels/conf.service.garage.instance.json"))
    svc = json.load(open(f"{TREE}/datamodels/conf.service.garage.json"))
    assert "storageshareuuid" in inst["properties"], "storage field missing"
    assert "storagesplit" in inst["properties"], "split flag missing"
    assert "enable" not in svc["properties"], "global service enable still present"
    rpcs = json.load(open(f"{TREE}/datamodels/rpc.garage.json"))
    ids = [m.get("id") for m in rpcs]
    assert "rpc.garage.setsettings" not in ids, "settings rpc still registered"


def test_workbench():
    import glob
    import yaml
    pages = glob.glob(f"{TREE}/workbench/component.d/*garage*.yaml")
    assert pages, "no garage components installed"

    def walk_columns(node, bad):
        if isinstance(node, dict):
            if "prop" in node and "name" in node and node.get("type") == "checkbox":
                bad.append(node.get("name"))
            for v in node.values():
                walk_columns(v, bad)
        elif isinstance(node, list):
            for v in node:
                walk_columns(v, bad)

    for page in pages:
        d = yaml.safe_load(open(page))
        bad = []
        walk_columns(d, bad)
        assert not bad, f"invalid checkbox column keys in {page}: {bad}"
    comp = " ".join(open(f).read() for f in pages)
    assert any("tabsPage" in open(f).read() for f in pages), \
        "details tabs page missing"
    assert not os.path.exists(
        f"{TREE}/workbench/component.d/omv-services-garage-settings-form-page.yaml"), \
        "settings page still present"


def test_compiled_frontend():
    import re
    src = open("/var/www/openmediavault/assets/route-config.json").read()
    assert "externalRedirect/%2Fgarage-sso%2F%3Finstance%3D" in src, \
        "web UI action not routed through externalRedirect"
    assert re.search(r'"lmdb",\s*"LMDB \(default\)"', src), \
        "database engine select pairs missing"
    assert '_("LMDB' not in src, "raw _() leaked into the select store"
    assert "tabsPage" in src, "details tabs page not compiled"


# ---------------------------------------------------------------- rpc

def test_port_suggest_and_bump():
    ports = free_port_set()
    for key in ("s3port", "rpcport", "webport", "adminport", "webuiport"):
        assert 1 <= ports[key] <= 65535, f"bad suggested {key}"
    share = share_uuid_by_name(SHARE_NAME)
    others = rpc("Garage", "getInstanceList", {"start": 0, "limit": -1})["data"]
    assert others, "need at least one existing instance for the bump test"
    taken = others[0]["s3port"]
    created = rpc("Garage", "setInstance",
                  make_instance_params("e2e-bump", share, s3port=taken))
    try:
        assert created["s3port"] != taken, \
            "duplicate port was not silently bumped on create"
    finally:
        rpc("Garage", "deleteInstance", {"uuid": created["uuid"]})


def test_storage_validation():
    share = share_uuid_by_name(SHARE_NAME)
    base = make_instance_params("e2e-val", share)
    bad = dict(base, storageshareuuid="")
    try:
        rpc("Garage", "setInstance", bad)
        raise AssertionError("empty storage share accepted")
    except RpcError:
        pass
    bad = dict(base, storagesplit=True, metadatashareuuid="")
    try:
        rpc("Garage", "setInstance", bad)
        raise AssertionError("split without metadata share accepted")
    except RpcError:
        pass
    created = rpc("Garage", "setInstance", dict(base, storageshareuuid=share))
    try:
        ds = {"uuid": NEW_UUID, "instanceuuid": created["uuid"],
              "shareuuid": share, "capacity": 10}
        try:
            rpc("Garage", "setDatastore", ds)
            raise AssertionError("storage share accepted as datastore")
        except RpcError:
            pass
    finally:
        rpc("Garage", "deleteInstance", {"uuid": created["uuid"]})


# ---------------------------------------------------------------- lifecycle

def test_lifecycle():
    share = share_uuid_by_name(SHARE_NAME)
    name = "e2e-life"
    bucket_name = f"e2e-bucket-{int(time.time())}"
    # Wipe storage from previous runs: garage metadata on the share would
    # make the fresh instance inherit old buckets and keys.
    storpath = get_share_path(share).rstrip("/")
    sh(f"rm -rf {shq(storpath + '/meta')} {shq(storpath + '/data')}")
    created = rpc("Garage", "setInstance",
                  make_instance_params(name, share, webui=True))
    uuid = created["uuid"]
    try:
        assert len(created["rpcsecret"]) == 64, "rpc secret not generated"
        assert len(created["admintoken"]) == 64, "admin token not generated"
        assert len(created["webuipassword"]) >= 16, "webui password not generated"
        apply_changes()
        wait_active(f"garage@{name}")
        toml = open(f"{ETC}/{name}.toml").read()
        storpath = get_share_path(share).rstrip("/")
        assert f'metadata_dir = "{storpath}/meta"' in toml, \
            "metadata_dir not on the storage subfolder"
        assert f'{{ path = "{storpath}/data", capacity' in toml, \
            "storage dataset lacks a capacity"
        secret = open(f"{ETC}/{name}.rpc_secret").read().strip()
        assert len(secret) == 64, "rendered rpc secret is empty"

        bucket = rpc("Garage", "setBucket", {
            "uuid": NEW_UUID, "instanceuuid": uuid, "name": bucket_name,
            "maxsize": 0, "maxobjects": 0, "website": False,
            "indexdoc": "index.html", "errordoc": ""})
        key = rpc("Garage", "setKey", {
            "uuid": NEW_UUID, "instanceuuid": uuid, "name": "e2e-key",
            "keyid": "", "secret": ""})
        bucket_uuid = get_list_uuid("getBucketList", bucket_name, uuid)
        key_uuid = get_list_uuid("getKeyList", "e2e-key", uuid)
        rpc("Garage", "setMapping", {
            "uuid": NEW_UUID, "instanceuuid": uuid, "keyuuid": key_uuid,
            "bucketuuid": bucket_uuid, "allowread": True,
            "allowwrite": True, "allowowner": True})
        if not SKIP_S3:
            s3_round_trip(key, bucket_name, created["s3port"])
        status = {i["name"]: i for i in
                  rpc("Garage", "getInstanceList",
                      {"start": 0, "limit": -1})["data"]}[name]
        assert status["status"] == "running", "instance status not running"
        assert status["storagesplit"] is False, "split flag wrong"
    finally:
        rpc("Garage", "deleteInstance", {"uuid": uuid})
        apply_changes()
        time.sleep(1)
    assert not os.path.exists(f"{ETC}/{name}.toml"), "toml not purged"
    assert not os.path.exists(f"{ETC}/{name}.rpc_secret"), "secret not purged"
    assert not os.path.exists(
        f"{NGINXD}/garage-webui-{name}.conf"), "nginx location not purged"
    assert sh(f"systemctl is-active garage@{name} 2>/dev/null",
              check=False) != "active", "unit still active after delete"
    acl = sh(f"getfacl -p {get_share_path(share)} 2>/dev/null")
    assert "user:garage" not in acl, "storage ACL not revoked"


def get_share_path(share_uuid):
    out = run(["salt-call", "--local", "--out=json",
               "omv_conf.get_sharedfolder_path", share_uuid]).stdout
    return json.loads(out)["local"]


def get_list_uuid(method, name, instance_uuid_):
    data = rpc("Garage", method,
               {"start": 0, "limit": -1, "instanceuuid": instance_uuid_})["data"]
    return next(x["uuid"] for x in data if x["name"] == name)


def s3_round_trip(key, bucket, port):
    env = dict(os.environ,
               AWS_ACCESS_KEY_ID=key["keyid"],
               AWS_SECRET_ACCESS_KEY=key["secret"])
    ep = f"http://127.0.0.1:{port}"
    subprocess.run(["aws", "--endpoint-url", ep, "s3", "cp",
                    "/etc/hostname", f"s3://{bucket}/e2e.txt"],
                   check=True, env=env, capture_output=True)
    subprocess.run(["aws", "--endpoint-url", ep, "s3api", "get-object",
                    "--bucket", bucket, "--key", "e2e.txt", "/tmp/e2e-dl"],
                   check=True, env=env, capture_output=True)
    assert open("/etc/hostname", "rb").read() == open("/tmp/e2e-dl", "rb").read(), \
        "S3 round trip content mismatch"


# ---------------------------------------------------------------- sso

def test_webui_env_and_sso():
    insts = rpc("Garage", "enumerateInstances")
    target = None
    for i in insts:
        row = rpc("Garage", "getInstance", {"uuid": i["uuid"]})
        if row.get("webuienable"):
            target = row
            break
    if target is None:
        print("SKIP webui/sso (no instance with web UI enabled)")
        return
    name = target["name"]
    env = open(f"{ETC}/{name}.webui.env").read()
    assert "AUTH_USER_PASS=admin:$2y$" in env or \
        "AUTH_USER_PASS=admin:$2" in env, \
        "webui env has an empty password hash"
    login = rpc("Garage", "getWebUiLogin", {"name": name})
    assert login["password"], "getWebUiLogin returned an empty password"
    try:
        req = urllib.request.Request(
            BASE + login["url"] + "api/auth/login",
            data=json.dumps({"username": login["username"],
                             "password": login["password"]}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode()
            assert r.status == 200, f"webui login returned {r.status}"
            assert r.headers.get("Set-Cookie") or body, \
                "webui login set neither a session cookie nor a body"
    except urllib.error.HTTPError as e:
        raise AssertionError(f"webui login failed: {e.code} {e.read()[:120]}")


def test_legacy_backfill():
    insts = rpc("Garage", "getInstanceList", {"start": 0, "limit": -1})["data"]
    for i in insts:
        assert "status" in i, "status column missing"
        assert isinstance(i["storagesplit"], bool), "storagesplit not backfilled"
        if i["storageshareuuid"]:
            assert len(i["storageshareuuid"]) == 36, "storage uuid malformed"


def cleanup_leftovers():
    for i in rpc("Garage", "enumerateInstances"):
        if i["name"].startswith("e2e-"):
            rpc("Garage", "deleteInstance", {"uuid": i["uuid"]})
    apply_changes()


# ---------------------------------------------------------------- main

def main():
    import yaml  # noqa: F401  (fail fast with a clear ImportError)
    cleanup_leftovers()
    tests = [
        ("datamodels", test_datamodels),
        ("workbench yaml", test_workbench),
        ("compiled frontend", test_compiled_frontend),
        ("port suggest + bump", test_port_suggest_and_bump),
        ("storage validation", test_storage_validation),
        ("lifecycle", test_lifecycle),
        ("webui env + sso chain", test_webui_env_and_sso),
        ("legacy backfill", test_legacy_backfill),
    ]
    for name, fn in tests:
        check(name, fn)
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
