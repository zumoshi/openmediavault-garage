"""Upgrading from a version that mirrored garage's buckets, keys and
permissions in confdb and had an admin API switch: the confdb migration
drops both, and running it again changes nothing."""

from garage_tester import instance

HELPERS = ". /usr/share/openmediavault/scripts/helper-functions"
# What postinst runs when upgrading from 0.1.0.
MIGRATE = "omv-confdbadm migrate conf.service.garage 0.1.0"
LEFTOVERS = ("/config/services/garage/buckets",
             "/config/services/garage/keys",
             "/config/services/garage/mappings",
             "/config/services/garage/instances/instance/adminenable")


def _garage_config(ssh) -> str:
    return ssh.out("xmlstarlet sel -t -c /config/services/garage "
                   "/etc/openmediavault/config.xml")


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
