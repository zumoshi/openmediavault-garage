"""Editing an existing instance: what the edit form posts must not break
the instance, and what it must not accept is rejected."""

import re
import secrets

import pytest

from garage_tester import ui
from garage_tester.rpc import RpcError

SERVER_OWNED = ("rpcsecret", "admintoken", "webuipassword",
                "webuipasswordhash", "webuiport")


def _confdb_instance(ssh, uuid: str) -> dict:
    return next(i for i in ssh.confdb("conf.service.garage.instance")
                if i["uuid"] == uuid)


def _confdb_names(ssh) -> list[str]:
    return [i["name"] for i in ssh.confdb("conf.service.garage.instance")]


def _form_params(page, cfg, name: str, uuid: str) -> dict:
    """The setInstance params the edit form posts for an unchanged instance."""
    ui.open_edit_form(page, cfg.host, uuid, name)
    ui.touch_form(page)
    return ui.capture_form_post(page)


def _set_instance_error(rpc, params: dict) -> str | None:
    """setInstance's error message, or None if it accepted `params`."""
    try:
        rpc.call("Garage", "setInstance", params)
    except RpcError as e:
        return str(e)
    return None


def _assert_port_rejected(error: str | None, port: int, conflict: str) -> None:
    assert error is not None, f"edit accepted port {port}, {conflict}"
    assert str(port) in error, \
        f"edit rejected port {port} ({conflict}) without naming it: {error}"


def _abbrev(value):
    return f"{value[:8]}... ({len(value)} chars)" if isinstance(value, str) \
        else value


def test_noop_edit_keeps_server_owned_fields(page, cfg, ssh, make_instance):
    name, info = make_instance(webui=True)
    before = _confdb_instance(ssh, info["uuid"])

    ui.open_edit_form(page, cfg.host, info["uuid"], name)
    ui.touch_form(page)
    ui.save_form(page)

    after = _confdb_instance(ssh, info["uuid"])
    changed = {f: (_abbrev(before[f]), _abbrev(after[f]))
               for f in SERVER_OWNED if before[f] != after[f]}
    assert not changed, \
        f"a no-op edit changed fields it never showed (before, after): {changed}"

    ui.apply_via_ui(page)
    ssh.wait_unit_running(f"omv-garage-webui@{name}")
    env = ssh.read_file(f"/etc/garage/{name}.webui.env")
    user_pass = re.search(r"^AUTH_USER_PASS=[^:\n]*:(.*)$", env, re.M)
    assert user_pass and user_pass.group(1).startswith("$2"), \
        f"web UI env has no password hash after a no-op edit: {env}"


def test_name_read_only_on_edit(page, cfg, make_instance):
    name, info = make_instance()
    ui.open_edit_form(page, cfg.host, info["uuid"], name)
    assert not ui.name_field(page).is_editable(), \
        "the Name field is editable on the edit form"


def test_rename_onto_existing_name_rejected(page, cfg, ssh, rpc,
                                            make_instance):
    taken, _ = make_instance()
    name, info = make_instance()
    params = _form_params(page, cfg, name, info["uuid"])

    error = _set_instance_error(rpc, {**params, "name": taken})
    names = _confdb_names(ssh)
    if error is None:
        rpc.call("Garage", "setInstance", params)
    assert error is not None, \
        f"renaming {name} onto {taken} was accepted, confdb names: {names}"
    assert len(names) == len(set(names)), f"duplicate names in confdb: {names}"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "REVIEW 2.10: edit-time port validation ignores collisions inside the "
    "same instance"))
def test_edit_rejects_port_used_twice_in_instance(page, cfg, rpc,
                                                  make_instance):
    name, info = make_instance()
    params = _form_params(page, cfg, name, info["uuid"])
    port = params["adminport"]
    error = _set_instance_error(rpc, {**params, "s3port": port})
    _assert_port_rejected(error, port, "the instance's own admin port")


def test_edit_rejects_port_of_other_instance(page, cfg, rpc, ssh,
                                             make_instance):
    _, other = make_instance()
    name, info = make_instance()
    port = _confdb_instance(ssh, other["uuid"])["s3port"]
    params = _form_params(page, cfg, name, info["uuid"])
    error = _set_instance_error(rpc, {**params, "s3port": port})
    _assert_port_rejected(error, port, "the S3 port of another instance")


@pytest.fixture()
def foreign_listener(ssh):
    """A process outside garage listening on a free loopback port."""
    while ssh.port_listening(port := 40000 + secrets.randbelow(10000)):
        pass
    pid = ssh.out(
        "setsid python3 -c 'import socket, time; s = socket.socket(); "
        f's.bind(("127.0.0.1", {port})); s.listen(); time.sleep(3600)\' '
        "</dev/null >/dev/null 2>&1 & echo $!")
    try:
        for _ in range(20):
            if ssh.port_listening(port):
                break
        else:
            raise RuntimeError(f"listener on {port} never came up")
        yield port
    finally:
        ssh.run(f"kill {pid}", check=False)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "REVIEW 2.10: edit-time port validation ignores ports held by other "
    "services"))
def test_edit_rejects_port_of_other_service(page, cfg, rpc, make_instance,
                                            foreign_listener):
    name, info = make_instance()
    params = _form_params(page, cfg, name, info["uuid"])
    error = _set_instance_error(rpc, {**params, "s3port": foreign_listener})
    _assert_port_rejected(error, foreign_listener,
                          "which another process is listening on")


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "REVIEW 2.8: s3region goes into the TOML unescaped and the datamodel "
    "accepts a double quote"))
def test_region_with_double_quote_rejected(page, cfg, rpc, make_instance):
    name, info = make_instance()
    params = _form_params(page, cfg, name, info["uuid"])
    region = 'gar"age'
    assert _set_instance_error(rpc, {**params, "s3region": region}) \
        is not None, f"setInstance accepted s3region {region}"
