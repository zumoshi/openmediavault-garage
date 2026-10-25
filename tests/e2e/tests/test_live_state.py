"""What the details page shows of garage's live state: buckets and keys
made outside OMV, their usage, and names that only need to be unique
per instance."""

import secrets
import time

import pytest

from garage_tester import instance, s3, ui
from garage_tester.instance import garage_json
from garage_tester.rpc import RpcError

LISTS = ["getBucketList", "getKeyList", "getMappingList"]


def _key_rows(rpc, uuid: str, keyid: str) -> list[dict]:
    listing = rpc.call("Garage", "getKeyList",
                       {"start": 0, "limit": -1, "instanceuuid": uuid})
    return [k for k in listing["data"] if k["keyid"] == keyid]


def _rpc_errors(bodies: dict[str, dict]) -> dict[str, str]:
    return {method: body["error"]["message"]
            for method, body in bodies.items() if body.get("error")}


def _webui_made_key(ssh, name: str) -> str:
    """Create a key directly against garage, as the garage web UI does."""
    return garage_json(ssh, name, "CreateKey",
                       {"name": f"gt-webui-{secrets.token_hex(3)}"})[
        "accessKeyId"]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "REVIEW 1.3: every tab's list RPC imports garage's state into confdb, "
    "and the tabs load at once, so a web UI-made key is imported several "
    "times"))
def test_details_page_imports_webui_key_once(page, cfg, ssh, rpc,
                                             make_instance):
    name, info = make_instance()
    keyid = _webui_made_key(ssh, name)

    bodies = ui.open_details(page, cfg.host, info["uuid"])

    rows = _key_rows(rpc, info["uuid"], keyid)
    errors = _rpc_errors(bodies)
    assert len(rows) == 1 and not errors, (
        f"after loading the details page, getKeyList has {len(rows)} rows "
        f"for key {keyid} (want 1); list RPC errors: {errors}")


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "REVIEW 1.3: concurrent list RPCs race on config.xml: duplicate key "
    "rows, and sometimes 'Document is empty'"))
def test_concurrent_list_rpcs(page, ssh, make_instance):
    name, info = make_instance()
    keyid = _webui_made_key(ssh, name)

    bodies = ui.rpc_concurrently(page, "Garage", LISTS, {
        "start": 0, "limit": -1, "instanceuuid": info["uuid"]})
    after = ui.rpc_concurrently(page, "Garage", ["getKeyList"], {
        "start": 0, "limit": -1, "instanceuuid": info["uuid"]})

    errors = _rpc_errors(bodies)
    keyids = [k["keyid"] for k in after["getKeyList"]["response"]["data"]]
    assert not errors and keyids.count(keyid) == 1, (
        f"concurrent {LISTS}: RPC errors {errors}; getKeyList then lists "
        f"key {keyid} {keyids.count(keyid)} times (want 1)")


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "REVIEW 2.4: bucket and key names are checked for uniqueness across "
    "all instances, not per instance"))
def test_same_names_on_two_instances(cfg, ssh, rpc, make_instance):
    bucket, key = "gt-same", "gt-same-key"
    made = [make_instance() for _ in range(2)]
    creds = {}
    for name, info in made:
        try:
            creds[name] = instance.setup_bucket_and_key(
                rpc, info["uuid"], bucket, key)
        except RpcError as e:
            creds[name] = e
    refused = {n: str(c) for n, c in creds.items() if isinstance(c, RpcError)}
    assert not refused, (
        f"bucket {bucket} and key {key} on a second instance were "
        f"refused: {refused}")

    for name, (key_id, secret) in creds.items():
        row = instance.instance_row(rpc, name)
        instance.wait_health(ssh, row["adminport"])
        s3.round_trip(f"http://{cfg.host}:{row['s3port']}", key_id, secret,
                      bucket, name.encode())


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "REVIEW 2.5: getBucketList matches live usage by global alias, so an "
    "alias-less bucket stays Pending with no usage"))
def test_aliasless_bucket_shows_usage(cfg, ssh, rpc, make_instance,
                                      s3_setup):
    name, info = make_instance()
    conn = s3_setup(name, info["uuid"])
    local = "gt-local"
    bucket = garage_json(ssh, name, "CreateBucket", {"localAlias": {
        "accessKeyId": conn["key_id"], "alias": local,
        "allow": {"read": True, "write": True, "owner": True}}})
    payload = b"alias-less bucket usage"
    s3.round_trip(conn["endpoint"], conn["key_id"], conn["secret"], local,
                  payload)
    usage = garage_json(ssh, name, "GetBucketInfo", {"id": bucket["id"]})
    assert (usage["objects"], usage["bytes"]) == (1, len(payload)), \
        f"garage itself reports {usage['objects']} objects, {usage['bytes']} bytes"

    listing = rpc.call("Garage", "getBucketList",
                       {"start": 0, "limit": -1, "instanceuuid": info["uuid"]})
    row = next(b for b in listing["data"] if b["garageid"] == bucket["id"])
    shown = {k: row.get(k) for k in ("name", "state", "objects", "bytes")}
    assert row["state"] != "Pending" and \
        (row.get("objects"), row.get("bytes")) == (1, len(payload)), (
            f"getBucketList shows alias-less bucket {bucket['id'][:12]} as "
            f"{shown}, garage reports 1 object of {len(payload)} bytes")


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "PLAN 3.3: list RPCs of a stopped instance show stale confdb rows "
    "instead of saying the instance is not running"))
def test_stopped_instance_rpcs_fail_fast(rpc, make_instance):
    name, info = make_instance(enabled=False)
    uuid = info["uuid"]
    listing = {"start": 0, "limit": -1, "instanceuuid": uuid}
    calls = {
        "getBucketList": listing,
        "getKeyList": listing,
        "getMappingList": listing,
        "setBucket": {"instanceuuid": uuid, "id": "", "name": "gt-stopped",
                      "maxsize": 0, "maxobjects": 0, "website": False,
                      "indexdoc": "", "errordoc": ""},
        "setKey": {"instanceuuid": uuid, "id": "", "name": "gt-stopped"},
        "setMapping": {"instanceuuid": uuid, "keyid": "GK0", "bucketid": "0",
                       "allowread": True, "allowwrite": False,
                       "allowowner": False},
    }
    answers = {}
    for method, params in calls.items():
        started = time.monotonic()
        try:
            rpc.call("Garage", method, params)
            message = "succeeded"
        except RpcError as e:
            message = str(e)
        answers[method] = (message, round(time.monotonic() - started, 1))
    wrong = {m: a for m, a in answers.items()
             if f"'{name}' is not running" not in a[0] or a[1] > 10}
    assert not wrong, (
        f"on stopped instance {name}, these did not fail within 10 s "
        f"saying it is not running (message, seconds): {wrong}")
