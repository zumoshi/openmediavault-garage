"""The basic flow the user described: make an instance in the browser,
then talk S3 to it."""

import secrets

from garage_tester import instance, s3, ui


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


def test_instances_table_columns_render(page, cfg, ssh):
    """ngx-datatable collapses columns without width or flexGrow to zero
    pixels. The user experienced exactly that: a table with only Name
    visible. Every configured column must render with real width."""
    ui.goto_instances(page, cfg.host)
    cells = page.locator("datatable-body-cell")
    cells.first.wait_for(state="visible", timeout=20000)
    n = cells.count()
    assert n == 6, f"expected 6 rendered cells, got {n}"
    widths = [cells.nth(i).evaluate("el => el.offsetWidth")
              for i in range(n)]
    assert all(w > 40 for w in widths), \
        f"collapsed table columns: {widths}"
