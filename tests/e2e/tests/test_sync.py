"""Bi-directional sync: changes made in the garage web UI (which talks
to the daemon's admin API directly, bypassing OMV) must show up in the
OMV lists, and deletions made there must disappear from OMV."""

import json

def _garage_json(ssh, name, endpoint, payload=None):
    payload_part = f" '{json.dumps(payload)}'" if payload else ""
    out = ssh.out(
        f"/usr/bin/garage -c /etc/garage/{name}.toml json-api "
        f"{endpoint}{payload_part}")
    return json.loads(out)


def _key_names(rpc, uuid):
    listing = rpc.call("Garage", "getKeyList",
                       {"start": 0, "limit": -1, "instanceuuid": uuid})
    return [k["name"] for k in listing["data"]]


def test_webui_created_key_imported(ssh, rpc, make_instance):
    name, info = make_instance(webui=False)
    uuid = info["uuid"]

    # Simulate the web UI: create a key directly against the daemon.
    _garage_json(ssh, name, "CreateKey", {"name": "gt-webui-made"})

    names = _key_names(rpc, uuid)
    assert "gt-webui-made" in names, \
        f"webui-created key not imported into OMV: {names}"


def test_webui_deleted_key_dropped(ssh, rpc, make_instance):
    name, info = make_instance(webui=False)
    uuid = info["uuid"]

    _garage_json(ssh, name, "CreateKey", {"name": "gt-doomed"})
    assert "gt-doomed" in _key_names(rpc, uuid)

    keyid = next(k["id"] for k in _garage_json(ssh, name, "ListKeys")
                 if k["name"] == "gt-doomed")
    _garage_json(ssh, name, "DeleteKey", {"id": keyid})

    names = _key_names(rpc, uuid)
    assert "gt-doomed" not in names, \
        f"webui-deleted key still visible in OMV: {names}"


def test_imported_key_retains_secret(ssh, rpc, make_instance):
    name, info = make_instance(webui=False)
    uuid = info["uuid"]

    _garage_json(ssh, name, "CreateKey", {"name": "gt-sec"})
    listing = rpc.call("Garage", "getKeyList",
                       {"start": 0, "limit": -1, "instanceuuid": uuid})
    row = next(k for k in listing["data"] if k["name"] == "gt-sec")
    assert len(row["secret"]) == 64, \
        "imported key secret was not recovered from garage"


def test_webui_created_bucket_imported(ssh, rpc, make_instance):
    """Buckets created outside OMV arrive two ways: with a garage global
    alias (imports under that alias) or alias-less like S3-created
    buckets (imports as imported-<id prefix>)."""
    name, info = make_instance(webui=False)
    uuid = info["uuid"]

    aliased = _garage_json(ssh, name, "CreateBucket", {"name": "gt-aliased"})
    _garage_json(ssh, name, "AddBucketAlias",
                 {"bucketId": aliased["id"], "globalAlias": "gt-aliased"})
    bare = _garage_json(ssh, name, "CreateBucket", {"name": "gt-bare"})

    listing = rpc.call("Garage", "getBucketList",
                       {"start": 0, "limit": -1, "instanceuuid": uuid})
    names = [b["name"] for b in listing["data"]]
    assert "gt-aliased" in names, \
        f"aliased bucket not imported under its alias: {names}"
    imported = [n for n in names if n.startswith("imported-")]
    assert len(imported) >= 1, \
        f"alias-less bucket not imported: {names}"


def test_import_reflects_permissions(ssh, rpc, make_instance, make_share):
    name, info = make_instance(webui=False, extra_datastore=True)
    uuid = info["uuid"]

    bucket = _garage_json(ssh, name, "CreateBucket",
                          {"name": "gt-perm-bkt"})
    key = _garage_json(ssh, name, "CreateKey", {"name": "gt-perm-key"})
    keyid = key["accessKeyId"]
    _garage_json(ssh, name, "AllowBucketKey", {
        "bucketId": bucket["id"], "accessKeyId": keyid,
        "permissions": {"read": True, "write": True, "owner": False}})

    listing = rpc.call("Garage", "getMappingList",
                       {"start": 0, "limit": -1, "instanceuuid": uuid})
    assert any(m["allowread"] and m["allowwrite"] and not m["allowowner"]
               for m in listing["data"]), \
        "imported key permissions did not become an OMV mapping"
