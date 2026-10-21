"""Playwright helpers for the OpenMediaVault workbench."""

import time

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

INSTANCES_URL = "/#/services/garage/instances"


def login(page: Page, host: str, password: str) -> None:
    page.goto(f"http://{host}/", wait_until="networkidle")
    page.get_by_role("textbox", name="User name").fill("admin")
    page.get_by_role("textbox", name="Password").fill(password)
    page.get_by_role("button", name="Log in").click()
    page.wait_for_timeout(2500)


def goto_instances(page: Page, host: str) -> None:
    page.goto(f"http://{host}{INSTANCES_URL}")
    page.get_by_role("button", name="Create").wait_for(
        state="visible", timeout=30000)


def create_instance(
    page: Page,
    name: str,
    storage_share: str,
    *,
    enabled: bool = True,
    webui: bool = False,
    split_meta_share: str | None = None,
    ports: dict[str, int] | None = None,
) -> None:
    """Fill the create form and save. Ports keys use the form labels."""
    page.get_by_role("button", name="Create").click()
    page.get_by_role("textbox", name="Name").wait_for(
        state="visible", timeout=20000)
    if not enabled:
        page.locator("label", has_text="Enabled").first.click()
    page.get_by_role("textbox", name="Name").fill(name)
    page.get_by_role("combobox", name="Storage shared folder").click()
    page.wait_for_timeout(600)
    page.locator(".cdk-overlay-container").get_by_text(
        storage_share, exact=True).first.click()
    page.wait_for_timeout(400)
    for label, port in (ports or {}).items():
        page.get_by_role("spinbutton", name=label).fill(str(port))
    if webui:
        page.locator("label", has_text="Enable web UI").first.click()
    if split_meta_share is not None:
        page.locator(
            "label", has_text="Separate metadata shared folder").first.click()
        page.wait_for_timeout(400)
        page.get_by_role("combobox", name="Metadata shared folder").click()
        page.wait_for_timeout(600)
        page.locator(".cdk-overlay-container").get_by_text(
            split_meta_share, exact=True).first.click()
    page.get_by_role("button", name="Save").click()
    # Either we are back at the table, or an error dialog appeared.
    try:
        page.get_by_role("button", name="Create").wait_for(
            state="visible", timeout=20000)
    except PlaywrightTimeout:
        body = page.locator("body").inner_text()
        raise AssertionError(f"instance creation did not finish: {body[:600]}")


def apply_via_ui(page: Page, timeout_s: int = 300) -> None:
    """Click the pending-changes Apply button and wait until it clears."""
    page.get_by_role("button", name="Apply").click(timeout=20000)
    page.get_by_role("dialog").wait_for(state="visible", timeout=20000)
    page.get_by_role("button", name="Yes").click()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        page.wait_for_timeout(3000)
        if page.get_by_text(
                "Pending configuration changes").count() == 0:
            return
        page.reload()
        page.wait_for_timeout(1500)
    raise AssertionError("pending changes banner never cleared")


def wait_unit_running(ssh, name: str, timeout_s: int = 240) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if ssh.unit_active(f"garage@{name}"):
            return
        time.sleep(3)
    raise AssertionError(f"garage@{name} never became active")


def select_row(page: Page, name: str) -> None:
    page.get_by_role("cell", name=name).click()


def open_webui(page: Page, name: str) -> Page:
    select_row(page, name)
    page.get_by_role("button", name="Open").click()
    with page.context.expect_page(timeout=30000) as popup_info:
        page.get_by_text("Web UI", exact=True).last.click()
    popup = popup_info.value
    popup.wait_for_load_state()
    popup.wait_for_timeout(4000)
    return popup


def delete_instance_via_ui(page: Page, name: str) -> None:
    select_row(page, name)
    page.get_by_role("button", name="Delete").click()
    page.get_by_role("button", name="Yes").click(timeout=20000)
