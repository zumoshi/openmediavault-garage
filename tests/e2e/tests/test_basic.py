"""The basic flow the user described: make an instance in the browser,
then talk S3 to it."""

from garage_tester import instance, s3, ui


def test_create_instance_via_ui_and_s3(
        page, cfg, ssh, shares, make_instance, s3_setup):
    name, info = make_instance(webui=True)

    assert ssh.unit_active(f"garage@{name}"), "garage unit not running"
    toml = instance.read_instance_toml(ssh, name)
    storpath = shares.path(info["storage_share"])
    assert toml["metadata_dir"] == f"{storpath}/meta"
    assert len(toml["data_dir"]) == 1
    assert toml["data_dir"][0]["path"] == f"{storpath}/data"
    assert int(toml["data_dir"][0]["capacity"].rstrip("GiB")) > 0

    conn = s3_setup(name, info["uuid"])
    s3.round_trip(conn["endpoint"], conn["key_id"], conn["secret"],
                  conn["bucket"], b"garage tester basic flow")


def test_instances_table_columns_render(page, cfg, ssh):
    """ngx-datatable collapses columns without width or flexGrow to zero
    pixels. The user experienced exactly that: a table with only Name
    visible. Every configured column must render with real width."""
    ui.goto_instances(page, cfg.host)
    rows = page.locator("datatable-body-row")
    rows.first.wait_for(state="visible", timeout=20000)
    widths = rows.evaluate_all("""rows => rows.map(r =>
        [...r.querySelectorAll('datatable-body-cell')].map(c => c.offsetWidth))""")
    for row in widths:
        assert len(row) == 6 and all(w > 40 for w in row), \
            f"every row needs 6 cells wider than 40px, got widths {widths}"
