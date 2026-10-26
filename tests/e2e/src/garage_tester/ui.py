"""Playwright helpers for the OpenMediaVault workbench."""

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, expect

INSTANCES_URL = "/#/services/garage/instances"
DETAILS_URL = "/#/services/garage/details"

# The list RPC behind each tab of the instance details page.
DETAILS_LISTS = ("getDatastoreList", "getBucketList", "getKeyList",
                 "getMappingList")


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


def open_details(page: Page, host: str, uuid: str,
                 timeout_s: int = 60) -> dict[str, dict]:
    """Open the instance details page and wait until every tab's list
    request has answered. Returns each list RPC's response body."""
    responses = {}

    def collect(response) -> None:
        if response.url.endswith("/rpc.php"):
            method = (response.request.post_data_json or {}).get("method")
            if method in DETAILS_LISTS:
                responses[method] = response

    page.on("response", collect)
    try:
        page.goto(f"http://{host}{DETAILS_URL}/{uuid}")
        for _ in range(timeout_s * 4):
            if len(responses) == len(DETAILS_LISTS):
                break
            page.wait_for_timeout(250)
        else:
            raise AssertionError(
                f"the details page never requested every tab's list, "
                f"answered: {sorted(responses)}")
    finally:
        page.remove_listener("response", collect)
    return {method: r.json() for method, r in responses.items()}


def name_field(page: Page):
    """The instance form's Name box. Exact, so "Web UI user name" never
    matches."""
    return page.get_by_role("textbox", name="Name", exact=True)


def _pick_option(page: Page, text: str, exact: bool = True) -> None:
    """Click `text` in the open select panel and wait for it to close."""
    option = page.locator(".cdk-overlay-container").get_by_text(
        text, exact=exact).first
    option.click()
    option.wait_for(state="hidden")


def pick(page: Page, combobox: str, option: str) -> None:
    """Open the select `combobox` and click the option containing
    `option`."""
    page.get_by_role("combobox", name=combobox).click()
    _pick_option(page, option, exact=False)


def create_instance(
    page: Page,
    name: str,
    storage_share: str,
    *,
    enabled: bool = True,
    webui: bool = False,
    split_meta_share: str | None = None,
    ports: dict[str, int] | None = None,
    storage_capacity: int | None = None,
) -> None:
    """Fill the create form and save. Ports keys use the form labels."""
    page.get_by_role("button", name="Create").click()
    name_field(page).wait_for(state="visible", timeout=20000)
    if not enabled:
        page.locator("label", has_text="Enabled").first.click()
    name_field(page).fill(name)
    page.get_by_role("combobox", name="Storage shared folder").click()
    _pick_option(page, storage_share)
    if storage_capacity is not None:
        page.get_by_role("spinbutton", name="Storage folder capacity (GiB)").fill(
            str(storage_capacity))
    for label, port in (ports or {}).items():
        page.get_by_role("spinbutton", name=label).fill(str(port))
    if webui:
        page.locator("label", has_text="Enable web UI").first.click()
    if split_meta_share is not None:
        page.locator(
            "label", has_text="Separate metadata shared folder").first.click()
        page.get_by_role("combobox", name="Metadata shared folder").click()
        _pick_option(page, split_meta_share)
    save_form(page)


def save_form(page: Page) -> None:
    """Click Save and wait until the workbench is back at the table."""
    page.get_by_role("button", name="Save").click()
    # Either we are back at the table, or an error dialog appeared.
    try:
        page.get_by_role("button", name="Create").wait_for(
            state="visible", timeout=20000)
    except PlaywrightTimeout:
        body = page.locator("body").inner_text()
        raise AssertionError(f"saving the form did not finish: {body[:600]}")


def open_edit_form(page: Page, host: str, uuid: str, name: str) -> None:
    page.goto(f"http://{host}{INSTANCES_URL}/edit/{uuid}")
    expect(name_field(page)).to_have_value(name, timeout=30000)


def touch_form(page: Page) -> None:
    """Make the open form dirty without changing a value. OMV keeps Save
    disabled on a pristine form, so this is what a no-op edit takes."""
    region = page.get_by_role("textbox", name="Region")
    value = region.input_value()
    region.fill("")
    region.fill(value)


def capture_form_post(page: Page) -> dict:
    """Click Save but drop the request. Returns the setInstance params
    exactly as the open form posts them."""
    def is_set(request) -> bool:
        return (request.url.endswith("/rpc.php")
                and (request.post_data_json or {}).get("method") == "setInstance")

    page.route("**/rpc.php", lambda route: route.abort() if is_set(route.request)
               else route.continue_())
    with page.expect_request(is_set) as request:
        page.get_by_role("button", name="Save").click()
    page.unroute("**/rpc.php")
    return request.value.post_data_json["params"]


def apply_via_ui(page: Page, timeout_s: int = 240) -> None:
    """Apply the pending changes through the banner."""
    _resolve_pending_changes(page, "Apply", timeout_s)


def undo_via_ui(page: Page, timeout_s: int = 120) -> None:
    """Undo the pending changes through the banner."""
    _resolve_pending_changes(page, "Undo", timeout_s)


def _resolve_pending_changes(page: Page, button: str, timeout_s: int) -> None:
    """Click `button` in the pending-changes banner, confirm, and wait
    until the banner clears. Fails as soon as OMV reports an error."""
    responses = []

    def collect(response) -> None:
        responses.append(response)

    page.on("response", collect)
    page.get_by_role("button", name=button).click(timeout=20000)
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
    finally:
        page.remove_listener("response", collect)
    if error.count():
        raise AssertionError(f"{button} failed: " + _failed_states(
            _rpc_error(responses) or error.first.text_content() or ""))
    # An expired OMV session drops the workbench to the login page, which
    # has no banner either.
    assert "#/login" not in page.url, f"OMV session expired during {button}"


def _rpc_error(responses) -> str | None:
    """The last RPC error message. The toast cuts it to about 1500 chars,
    which on a failed apply is Salt's first few, passing, states."""
    messages = []
    for response in responses:
        if not response.url.endswith("/rpc.php"):
            continue
        try:
            body = response.json()
        except Exception:  # a body that is gone or not JSON has no error
            continue
        if isinstance(body, dict) and (body.get("error") or {}).get("message"):
            messages.append(body["error"]["message"])
    return messages[-1] if messages else None


def _failed_states(message: str) -> str:
    """A failed apply reports Salt's whole run. Keep the states that failed."""
    failed = [b.strip() for b in message.split("----------")
              if "Result: False" in b]
    return "\n----------\n".join(failed)[:3000] if failed else message[:600]


def details_tab(page: Page, host: str, uuid: str, tab: str):
    """Open one tab of the instance details page. Returns the tab panel
    once its table has loaded."""
    if f"{DETAILS_URL}/{uuid}" not in page.url:
        page.goto(f"http://{host}{DETAILS_URL}/{uuid}")
    page.get_by_role("tab", name=tab).click()
    panel = page.get_by_role("tabpanel", name=tab)
    panel.get_by_role("table").wait_for(state="visible", timeout=30000)
    return panel


def save_details_form(page: Page) -> None:
    """Click Save on a bucket, key or permission form and wait until the
    workbench is back on the details page."""
    page.get_by_role("button", name="Save").click()
    try:
        page.wait_for_url(lambda url: "/services/garage/details/" in url,
                          timeout=30000)
    except PlaywrightTimeout:
        body = page.locator("body").inner_text()
        raise AssertionError(f"saving the form did not finish: {body[:600]}")


def delete_row(page: Page, panel, cell: str) -> None:
    """Select the row with `cell` in `panel`, delete it and confirm."""
    panel.get_by_role("cell", name=cell, exact=True).click()
    panel.get_by_role("button", name="Delete").click()
    page.get_by_role("button", name="Yes").click(timeout=20000)
    panel.get_by_role("cell", name=cell, exact=True).wait_for(
        state="detached", timeout=30000)


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


def rpc_concurrently(page: Page, service: str, methods: list[str],
                     params: dict) -> dict[str, dict]:
    """Post one RPC per method at once from the logged-in page, the way a
    tabs page loads its tabs. Returns each method's response body."""
    bodies = page.evaluate("""([service, methods, params]) => Promise.all(
        methods.map(method => fetch('/rpc.php', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({service, method, params}),
        }).then(r => r.json())))""", [service, methods, params])
    return dict(zip(methods, bodies))
