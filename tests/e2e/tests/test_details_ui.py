"""Datastores, buckets, access keys and permissions made, changed and
removed through the instance details page, checked against what garage
itself reports."""

import time

from playwright.sync_api import expect

from garage_tester import ui
from garage_tester.instance import garage_json

GIB = 1024 ** 3


def _bucket(ssh, name: str, alias: str) -> dict | None:
    for bucket in garage_json(ssh, name, "ListBuckets"):
        if alias in bucket["globalAliases"]:
            return garage_json(ssh, name, "GetBucketInfo", {"id": bucket["id"]})
    return None


def _key(ssh, name: str, key_name: str) -> dict | None:
    for key in garage_json(ssh, name, "ListKeys"):
        if key["name"] == key_name:
            return garage_json(ssh, name, "GetKeyInfo",
                               {"id": key["id"], "showSecretKey": True})
    return None


def _permissions(ssh, name: str, bucket_alias: str, key_id: str) -> dict:
    keys = _bucket(ssh, name, bucket_alias)["keys"]
    return next((k["permissions"] for k in keys
                 if k["accessKeyId"] == key_id), {})


def test_bucket_key_permission_round_trip(page, cfg, ssh, make_instance):
    name, info = make_instance()
    host, uuid = cfg.host, info["uuid"]
    bucket, key = "gt-ui-bucket", "gt-ui-key"

    panel = ui.details_tab(page, host, uuid, "Buckets")
    panel.get_by_role("button", name="Create").click()
    page.get_by_role("textbox", name="Name", exact=True).fill(bucket)
    page.get_by_role("spinbutton", name="Maximum size (GiB)").fill("2")
    ui.save_details_form(page)
    made = _bucket(ssh, name, bucket)
    assert made and made["quotas"]["maxSize"] == 2 * GIB, \
        f"garage after creating bucket {bucket} in the UI: {made}"

    panel = ui.details_tab(page, host, uuid, "Buckets")
    panel.get_by_role("cell", name=bucket, exact=True).click()
    panel.get_by_role("button", name="Edit").click()
    expect(page.get_by_role("spinbutton", name="Maximum size (GiB)")
           ).to_have_value("2", timeout=30000)
    page.get_by_role("spinbutton", name="Maximum objects").fill("50")
    ui.save_details_form(page)
    quotas = _bucket(ssh, name, bucket)["quotas"]
    assert quotas == {"maxSize": 2 * GIB, "maxObjects": 50}, \
        f"garage quotas after editing bucket {bucket} in the UI: {quotas}"

    panel = ui.details_tab(page, host, uuid, "Access keys")
    panel.get_by_role("button", name="Create").click()
    page.get_by_role("textbox", name="Name", exact=True).fill(key)
    ui.save_details_form(page)
    made_key = _key(ssh, name, key)
    assert made_key, f"garage has no key {key} after creating it in the UI"

    panel = ui.details_tab(page, host, uuid, "Access keys")
    panel.get_by_role("cell", name=key, exact=True).click()
    panel.get_by_role("button", name="Edit").click()
    expect(page.get_by_role("textbox", name="Secret", exact=True)
           ).to_have_value(made_key["secretAccessKey"], timeout=30000)
    page.get_by_role("textbox", name="Name", exact=True).fill(f"{key}-2")
    ui.save_details_form(page)
    key = f"{key}-2"
    assert _key(ssh, name, key), f"garage has no key renamed to {key}"
    key_id = made_key["accessKeyId"]

    panel = ui.details_tab(page, host, uuid, "Permissions")
    panel.get_by_role("button", name="Create").click()
    ui.pick(page, "Access key", key)
    ui.pick(page, "Bucket", bucket)
    ui.save_details_form(page)
    perms = _permissions(ssh, name, bucket, key_id)
    assert perms == {"read": True, "write": True, "owner": False}, \
        f"garage permissions after granting read and write in the UI: {perms}"

    panel = ui.details_tab(page, host, uuid, "Permissions")
    panel.get_by_role("cell", name=key, exact=True).click()
    panel.get_by_role("button", name="Edit").click()
    expect(page.get_by_role("checkbox", name="Read")).to_be_checked(
        timeout=30000)
    page.locator("label", has_text="Owner").first.click()
    page.locator("label", has_text="Write").first.click()
    ui.save_details_form(page)
    perms = _permissions(ssh, name, bucket, key_id)
    assert perms == {"read": True, "write": False, "owner": True}, \
        f"garage permissions after editing to read and owner: {perms}"

    panel = ui.details_tab(page, host, uuid, "Permissions")
    ui.delete_row(page, panel, key)
    perms = _permissions(ssh, name, bucket, key_id)
    assert not any(perms.values()), \
        f"garage permissions after deleting the permission in the UI: {perms}"

    panel = ui.details_tab(page, host, uuid, "Access keys")
    ui.delete_row(page, panel, key)
    assert _key(ssh, name, key) is None, \
        f"garage still has key {key} after deleting it in the UI"

    panel = ui.details_tab(page, host, uuid, "Buckets")
    ui.delete_row(page, panel, bucket)
    assert _bucket(ssh, name, bucket) is None, \
        f"garage still has bucket {bucket} after deleting it in the UI"


def _edit_bucket(page, host: str, uuid: str, label: str) -> None:
    panel = ui.details_tab(page, host, uuid, "Buckets")
    panel.get_by_role("cell", name=label, exact=True).click()
    panel.get_by_role("button", name="Edit").click()
    expect(page.get_by_role("spinbutton", name="Maximum objects")
           ).to_be_visible(timeout=30000)


def test_aliasless_bucket_edited_named_and_renamed_via_ui(page, cfg, ssh,
                                                          make_instance):
    name, info = make_instance()
    host, uuid = cfg.host, info["uuid"]
    bucket_id = garage_json(ssh, name, "CreateBucket",
                            {"globalAlias": None})["id"]

    def bucket() -> dict:
        return garage_json(ssh, name, "GetBucketInfo", {"id": bucket_id})

    _edit_bucket(page, host, uuid, bucket_id[:16])
    expect(page.get_by_role("textbox", name="Name", exact=True)).to_have_value("")
    page.get_by_role("spinbutton", name="Maximum objects").fill("5")
    ui.save_details_form(page)
    got = bucket()
    assert (got["globalAliases"], got["quotas"]["maxObjects"]) == ([], 5), \
        f"garage after setting a quota on the alias-less bucket: {got}"

    _edit_bucket(page, host, uuid, bucket_id[:16])
    page.get_by_role("textbox", name="Name", exact=True).fill("gt-named")
    ui.save_details_form(page)
    assert bucket()["globalAliases"] == ["gt-named"], \
        f"garage aliases after naming the bucket: {bucket()['globalAliases']}"

    _edit_bucket(page, host, uuid, "gt-named")
    page.get_by_role("textbox", name="Name", exact=True).fill("gt-renamed")
    ui.save_details_form(page)
    got = bucket()
    assert (got["globalAliases"], got["quotas"]["maxObjects"]) == \
        (["gt-renamed"], 5), f"garage after renaming the bucket: {got}"


def test_datastore_edited_and_removed_through_the_ui(page, cfg, ssh,
                                                     make_instance):
    name, info = make_instance(extra_datastore=True)
    share = info["datastore_share"]
    panel = ui.details_tab(page, cfg.host, info["uuid"], "Datastores")

    panel.get_by_role("cell", name=share, exact=True).click()
    panel.get_by_role("button", name="Edit").click()
    expect(page.get_by_role("combobox", name="Shared folder")).to_be_disabled()
    page.get_by_label("Capacity (GiB)").fill("7")
    page.get_by_role("button", name="Save").click()
    page.wait_for_url(f"**/details/{info['uuid']}", timeout=30000)
    panel = ui.details_tab(page, cfg.host, info["uuid"], "Datastores")
    expect(panel.get_by_role("cell", name="7", exact=True)).to_be_visible()

    panel.get_by_role("cell", name=share, exact=True).click()
    panel.get_by_role("button", name="Delete").click()
    expect(page.get_by_text("Removing a datastore takes two deletes")) \
        .to_be_visible()
    page.get_by_role("button", name="Yes").click()
    expect(panel.get_by_text("the data moves once the change is applied")) \
        .to_be_visible(timeout=30000)

    ui.apply_via_ui(page)
    deadline = time.time() + 180
    while True:
        page.reload()
        panel = ui.details_tab(page, cfg.host, info["uuid"], "Datastores")
        status = panel.get_by_role("row").filter(has_text=share).inner_text()
        if "Empty: delete it again" in status:
            break
        assert time.time() < deadline, f"datastore not drained: {status}"
        time.sleep(5)

    ui.delete_row(page, panel, share)
    ui.apply_via_ui(page)
    toml = ssh.read_file(f"/etc/garage/{name}.toml")
    assert f"{share}/" not in toml, "the removed datastore is still a data_dir"
