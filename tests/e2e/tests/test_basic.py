"""The basic flow the user described: make an instance in the browser,
then talk S3 to it."""

import secrets

from garage_tester import instance, s3


def test_create_instance_via_ui_and_s3(
        page, cfg, ssh, rpc, make_instance, s3_setup):
    name, info = make_instance(webui=True)
    s3_port = instance.instance_ports(rpc, name)["s3"]

    assert ssh.unit_active(f"garage@{name}"), "garage unit not running"
    toml = instance.read_instance_toml(ssh, name)
    storpath = instance.share_path(ssh, info["storage_share"]).rstrip("/")
    assert toml["metadata_dir"] == f"{storpath}/meta"
    assert len(toml["data_dir"]) == 1
    assert toml["data_dir"][0]["path"] == f"{storpath}/data"
    assert int(toml["data_dir"][0]["capacity"].rstrip("GiB")) > 0

    conn = s3_setup(name, info["uuid"], s3_port)
    s3.round_trip(cfg.host, s3_port, conn["key_id"], conn["secret"],
                  conn["bucket"], b"garage tester basic flow")
