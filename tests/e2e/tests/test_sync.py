"""Changes made in the garage web UI, which talks to the daemon's admin
API directly and bypasses OMV, show up in the OMV lists, and deletions
made there disappear from them. Garage is the only owner of buckets,
keys and permissions, so there is nothing to import or reconcile."""

from garage_tester.instance import garage_json


def _list(rpc, method, uuid):
    return rpc.call("Garage", method,
                    {"start": 0, "limit": -1, "instanceuuid": uuid})["data"]


def test_webui_created_key_listed(ssh, rpc, make_instance):
    name, info = make_instance(webui=False)

    key = garage_json(ssh, name, "CreateKey", {"name": "gt-webui-made"})

    rows = _list(rpc, "getKeyList", info["uuid"])
    assert {"id": key["accessKeyId"], "name": "gt-webui-made"} in rows, \
        f"web UI-made key missing from getKeyList: {rows}"


def test_webui_deleted_key_disappears(ssh, rpc, make_instance):
    name, info = make_instance(webui=False)
    key = garage_json(ssh, name, "CreateKey", {"name": "gt-doomed"})
    assert any(k["id"] == key["accessKeyId"]
               for k in _list(rpc, "getKeyList", info["uuid"]))

    garage_json(ssh, name, "DeleteKey", {"id": key["accessKeyId"]})

    rows = _list(rpc, "getKeyList", info["uuid"])
    assert not any(k["id"] == key["accessKeyId"] for k in rows), \
        f"web UI-deleted key still listed: {rows}"


def test_key_secret_only_from_its_own_page(ssh, rpc, make_instance):
    name, info = make_instance(webui=False)
    key = garage_json(ssh, name, "CreateKey", {"name": "gt-sec"})

    rows = _list(rpc, "getKeyList", info["uuid"])
    opened = rpc.call("Garage", "getKey", {"instanceuuid": info["uuid"],
                                           "id": key["accessKeyId"]})

    leaked = [row for row in rows if "secret" in row]
    assert not leaked, f"getKeyList returns secrets: {leaked}"
    assert opened["secret"] == key["secretAccessKey"], \
        "getKey does not return the secret garage holds for the key"


def test_webui_created_buckets_listed(ssh, rpc, make_instance):
    """Buckets made outside OMV come with a global alias, listed under
    it, or without one like S3-created buckets, listed under the start
    of their id."""
    name, info = make_instance(webui=False)
    aliased = garage_json(ssh, name, "CreateBucket", {"globalAlias": None})
    garage_json(ssh, name, "AddBucketAlias",
                {"bucketId": aliased["id"], "globalAlias": "gt-aliased"})
    bare = garage_json(ssh, name, "CreateBucket", {"globalAlias": None})

    labels = {b["id"]: b["label"]
              for b in _list(rpc, "getBucketList", info["uuid"])}
    assert labels.get(aliased["id"]) == "gt-aliased", \
        f"aliased bucket not listed under its alias: {labels}"
    assert labels.get(bare["id"]) == bare["id"][:16], \
        f"alias-less bucket not listed under its id: {labels}"


def test_webui_made_permission_listed(ssh, rpc, make_instance):
    name, info = make_instance(webui=False)
    bucket = garage_json(ssh, name, "CreateBucket", {"globalAlias": None})
    key = garage_json(ssh, name, "CreateKey", {"name": "gt-perm-key"})
    garage_json(ssh, name, "AllowBucketKey", {
        "bucketId": bucket["id"], "accessKeyId": key["accessKeyId"],
        "permissions": {"read": True, "write": True, "owner": False}})

    rows = [(m["keyid"], m["bucketid"], m["allowread"], m["allowwrite"],
             m["allowowner"]) for m in _list(rpc, "getMappingList", info["uuid"])]
    assert rows == [(key["accessKeyId"], bucket["id"], True, True, False)], \
        f"getMappingList after granting read and write in garage: {rows}"
