"""Playwright helpers for the OpenMediaVault workbench."""

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

INSTANCES_URL = "/#/services/garage/instances"


def login(page: Page, host: str, password: str) -> None:
    page.goto(f"http://{host}/", wait_until="networkidle")
    page.get_by_role("textbox", name="User name").fill("admin")
    page.get_by_role("textbox", name="Password").fill(password)
    page.get_by_role("button", name="Log in").click()
    page.wait_for_url(lambda url: url.endswith("#/dashboard"))


def goto_instances(page: Page, host: str) -> None:
    page.goto(f"http://{host}{INSTANCES_URL}")
    page.get_by_role("button", name="Create").wait_for(
        state="visible", timeout=30000)


def _pick_option(page: Page, text: str) -> None:
    """Click `text` in the open select panel and wait for it to close."""
    option = page.locator(".cdk-overlay-container").get_by_text(
        text, exact=True).first
    option.click()
    option.wait_for(state="hidden")


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
    _pick_option(page, storage_share)
    for label, port in (ports or {}).items():
        page.get_by_role("spinbutton", name=label).fill(str(port))
    if webui:
        page.locator("label", has_text="Enable web UI").first.click()
    if split_meta_share is not None:
        page.locator(
            "label", has_text="Separate metadata shared folder").first.click()
        page.get_by_role("combobox", name="Metadata shared folder").click()
        _pick_option(page, split_meta_share)
    page.get_by_role("button", name="Save").click()
    # Either we are back at the table, or an error dialog appeared.
    try:
        page.get_by_role("button", name="Create").wait_for(
            state="visible", timeout=20000)
    except PlaywrightTimeout:
        body = page.locator("body").inner_text()
        raise AssertionError(f"instance creation did not finish: {body[:600]}")


def apply_via_ui(page: Page, timeout_s: int = 240) -> None:
    """Click the pending-changes Apply button and wait until the banner
    clears. Fails as soon as OMV reports the apply failed."""
    page.get_by_role("button", name="Apply").click(timeout=20000)
    page.get_by_role("dialog").wait_for(state="visible", timeout=20000)
    page.get_by_role("button", name="Yes").click()
    error = page.locator("#toast-container .toast-error")
    try:
        page.wait_for_function("""() =>
            document.querySelector('#toast-container .toast-error')
            || !document.body.innerText.includes('Pending configuration changes')
            """, timeout=timeout_s * 1000)
    except PlaywrightTimeout:
        body = page.locator("body").inner_text()
        raise AssertionError(f"pending changes banner never cleared: {body[:600]}")
    if error.count():
        raise AssertionError(f"apply failed: {(error.first.text_content() or '')[:600]}")
    # An expired OMV session drops the workbench to the login page, which
    # has no banner either.
    assert "#/login" not in page.url, "OMV session expired during apply"


def select_row(page: Page, name: str) -> None:
    page.get_by_role("cell", name=name).click()


def open_webui(page: Page, name: str) -> Page:
    select_row(page, name)
    page.get_by_role("button", name="Open").click()
    with page.context.expect_page(timeout=30000) as popup_info:
        page.get_by_text("Web UI", exact=True).last.click()
    popup = popup_info.value
    popup.wait_for_load_state()
    return popup


def delete_instance_via_ui(page: Page, name: str) -> None:
    select_row(page, name)
    page.get_by_role("button", name="Delete").click()
    page.get_by_role("button", name="Yes").click(timeout=20000)
