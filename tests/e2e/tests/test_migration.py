"""Upgrading from pre-release versions: the confdb migration drops the
confdb mirror of garage's buckets, keys and permissions and the admin API
switch, fills in the storage share of rows that only name a metadata
share, and running it again changes nothing."""

from xml.etree.ElementTree import canonicalize

from garage_tester import instance

HELPERS = ". /usr/share/openmediavault/scripts/helper-functions"
# What postinst runs when upgrading from 0.1.0.
MIGRATE = "omv-confdbadm migrate conf.service.garage 0.1.0"
LEFTOVERS = ("/config/services/garage/buckets",
             "/config/services/garage/keys",
             "/config/services/garage/mappings",
             "/config/services/garage/instances/instance/adminenable")


def _config(ssh, xpath: str) -> str:
    """The nodes at `xpath`, ignoring the indentation the OMV helpers
    rewrite on every edit."""
    xml = ssh.out(f"xmlstarlet sel -t -c \"{xpath}\" "
                  "/etc/openmediavault/config.xml")
    return canonicalize(f"<r>{xml}</r>", strip_text=True)


def _garage_config(ssh) -> str:
    return _config(ssh, "/config/services/garage")


def _count(ssh, xpath: str) -> int:
    return int(ssh.out(f"xmlstarlet sel -t -v 'count({xpath})' "
                       "/etc/openmediavault/config.xml"))


def test_migration_drops_mirror_and_admin_switch(ssh, rpc, make_instance):
    name, info = make_instance()
    row = f"/config/services/garage/instances/instance[uuid='{info['uuid']}']"
    ssh.out(f"""{HELPERS}
        for tree in buckets keys mappings; do
            omv_config_exists /config/services/garage/$tree ||
                omv_config_add_node /config/services/garage $tree
        done
        omv_config_add_node /config/services/garage/buckets bucket
        omv_config_add_key /config/services/garage/buckets/bucket instanceuuid {info['uuid']}
        omv_config_add_key /config/services/garage/buckets/bucket name gt-legacy
        omv_config_exists "{row}/adminenable" ||
            omv_config_add_key "{row}" adminenable 0
        omv_config_update "{row}/adminenable" 0""")

    ssh.out(MIGRATE)
    once = _garage_config(ssh)
    ssh.out(MIGRATE)
    twice = _garage_config(ssh)

    left = {xpath: n for xpath in LEFTOVERS if (n := _count(ssh, xpath))}
    assert not left, f"nodes left after the migration (xpath: count): {left}"
    assert once == twice, "a second migration run changed the config"

    rpc.apply(["garage"])
    ssh.wait_unit_running(f"garage@{name}")
    admin = instance.read_instance_toml(ssh, name).get("admin", {})
    port = instance.instance_row(rpc, name)["adminport"]
    assert admin.get("api_bind_addr") == f"127.0.0.1:{port}", \
        f"[admin] of {name} after the migration: {admin}"
    instance.wait_health(ssh, port)


def test_migration_fills_storage_of_prerelease_row(ssh, rpc, make_instance,
                                                   shares):
    """A pre-release row names only a metadata share. The migration turns
    it into a split instance whose storage share is that same share, so it
    deploys where the pre-release put it: metadata at the share root, data
    on the datastores. Other rows are left alone. Without a datastore the
    render hits REVIEW 2.7, which test_split_storage covers."""
    name, info = make_instance(extra_datastore=True)
    uuid = info["uuid"]
    share_uuid = shares.uuid_by_name(info["storage_share"])
    row = f"/config/services/garage/instances/instance[uuid='{uuid}']"
    others = f"/config/services/garage/instances/instance[uuid!='{uuid}']"
    ssh.out(f"""{HELPERS}
        omv_config_delete "{row}/metadatashareuuid"
        omv_config_delete "{row}/storageshareuuid"
        omv_config_delete "{row}/storagesplit"
        omv_config_add_key "{row}" metadatashareuuid {share_uuid}""")
    others_before = _config(ssh, others)

    ssh.out(MIGRATE)
    once = _garage_config(ssh)
    ssh.out(MIGRATE)
    twice = _garage_config(ssh)

    migrated = next(i for i in ssh.confdb("conf.service.garage.instance")
                    if i["uuid"] == uuid)
    assert (migrated["storageshareuuid"], migrated["storagesplit"]) == \
        (share_uuid, True), f"migrated row: {migrated}"
    assert once == twice, "a second migration run changed the config"
    assert _config(ssh, others) == others_before, \
        "the migration changed rows that already name a storage share"

    rpc.apply(["garage"])
    ssh.wait_unit_running(f"garage@{name}")
    toml = instance.read_instance_toml(ssh, name)
    paths = (toml["metadata_dir"],
             [d["path"].rstrip("/") for d in toml["data_dir"]])
    assert paths == (shares.path(info["storage_share"]) + "/",
                     [shares.path(info["datastore_share"])]), \
        f"{name}.toml: {toml}"
