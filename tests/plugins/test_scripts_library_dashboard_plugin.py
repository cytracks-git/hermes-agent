"""Scripts library dashboard plugin — REST surface.

The router mounts at ``/api/plugins/scripts-library/`` inside the dashboard's
FastAPI app; here it is attached to a bare FastAPI instance so the REST contract
is provable without booting the dashboard (same harness shape as
``tests/plugins/test_kanban_dashboard_plugin.py``).

The negative controls carry the weight: this surface reads files, so the tests
that matter are the ones that try to make it read the wrong file.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_API = REPO_ROOT / "plugins" / "scripts-library" / "dashboard" / "plugin_api.py"


def _load_plugin_module():
    spec = importlib.util.spec_from_file_location("scripts_library_plugin_api", PLUGIN_API)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    (home / "scripts").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))

    module = _load_plugin_module()
    # The catalogue must describe THIS temp home, not the checkout Hermes runs
    # from, so the repo root and user config are pinned to nothing.
    monkeypatch.setattr(module, "_repo_root", lambda: None)
    monkeypatch.setattr(module, "_config", lambda: {})
    module._cache.clear()
    return module


@pytest.fixture
def client(plugin):
    app = FastAPI()
    app.include_router(plugin.router)
    return TestClient(app)


@pytest.fixture
def scripts_dir(tmp_path):
    return tmp_path / "hermes" / "scripts"


def _write(path: Path, content: str, *, mode: int = 0o644) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)
    return path


# --- Catalogue --------------------------------------------------------------


def test_empty_catalog_still_reports_where_it_looked(client):
    body = client.get("/catalog").json()

    assert body["scripts"] == []
    assert body["roots"], "an empty catalogue must still name its roots"
    assert body["total"] == 0


def test_catalog_lists_a_script_with_its_purpose_and_run_command(client, scripts_dir):
    _write(scripts_dir / "rotate.sh", "#!/usr/bin/env bash\n# Rotate gateway logs.\n", mode=0o755)

    body = client.get("/catalog").json()

    assert body["total"] == 1
    entry = body["scripts"][0]
    assert entry["name"] == "rotate.sh"
    assert entry["purpose"] == "Rotate gateway logs."
    assert entry["run_command"].endswith("rotate.sh")


def test_search_filters_on_purpose_not_just_filename(client, scripts_dir):
    _write(scripts_dir / "a.sh", "#!/bin/sh\n# Rotate gateway logs.\n")
    _write(scripts_dir / "b.sh", "#!/bin/sh\n# Send a weekly digest.\n")

    body = client.get("/catalog", params={"q": "digest"}).json()

    assert [entry["name"] for entry in body["scripts"]] == ["b.sh"]
    # `total` stays the size of the catalogue so the UI can say "1 of 2".
    assert (body["matched"], body["total"]) == (1, 2)


def test_search_that_matches_nothing_returns_empty_not_everything(client, scripts_dir):
    """NEGATIVE CONTROL: a filter that silently falls back to 'all' is worse
    than no filter, because it looks like it worked."""
    _write(scripts_dir / "a.sh", "#!/bin/sh\n# Rotate gateway logs.\n")

    body = client.get("/catalog", params={"q": "nonexistent-term-xyz"}).json()

    assert body["scripts"] == []
    assert body["matched"] == 0


def test_language_filter_discriminates(client, scripts_dir):
    _write(scripts_dir / "a.py", "'''Python one.'''\n")
    _write(scripts_dir / "b.sh", "#!/bin/sh\n# Shell one.\n")

    assert [e["name"] for e in client.get("/catalog", params={"language": "python"}).json()["scripts"]] == ["a.py"]
    assert [e["name"] for e in client.get("/catalog", params={"language": "shell"}).json()["scripts"]] == ["b.sh"]


# --- Detail and the id gate -------------------------------------------------


def test_detail_returns_documentation_sections_and_lifecycle(client, scripts_dir):
    _write(
        scripts_dir / "metrics.py",
        '"""Collect metrics.\n\nUsage:\n  metrics.py --since 7d\n\nExit codes:\n  0 ok\n  2 unreachable\n"""\n',
    )
    script_id = client.get("/catalog").json()["scripts"][0]["id"]

    body = client.get(f"/scripts/{script_id}").json()

    assert body["purpose"] == "Collect metrics."
    assert "metrics.py --since 7d" in body["sections"]["usage"]
    assert "2 unreachable" in body["sections"]["exit_codes"]
    assert body["lifecycle"]["stages"]


def test_unknown_id_is_404(client):
    assert client.get("/scripts/deadbeefdeadbeef").status_code == 404


def test_a_path_cannot_be_smuggled_in_place_of_an_id(client, plugin, scripts_dir, tmp_path):
    """NEGATIVE CONTROL — traversal. The id is opaque and resolved against the
    catalogue, so a path-shaped id names nothing whatever it points at.

    The gate is asserted DIRECTLY (``_entry_or_404``) as well as over HTTP:
    URL-shaped probes are mostly answered by the router before the handler ever
    runs, so an HTTP-only test would be measuring FastAPI's path matching and
    would stay green even with the gate removed (proven by mutation).
    """
    from fastapi import HTTPException

    secret = tmp_path / "secret.py"
    secret.write_text("SECRET = 'hunter2'\n", encoding="utf-8")
    _write(scripts_dir / "real.py", "'''Real.'''\n")
    # Warm the catalogue so the gate is rejecting against a populated scan,
    # not an empty one.
    assert client.get("/catalog").json()["total"] == 1

    for smuggled in (str(secret), "../../../../etc/passwd", "/etc/passwd", "real.py", "scripts/real.py"):
        with pytest.raises(HTTPException) as excinfo:
            plugin._entry_or_404(smuggled)
        assert excinfo.value.status_code == 404, smuggled

    for attempt in ("../../../../etc/passwd", "..%2F..%2Fetc%2Fpasswd", str(secret), "/etc/passwd"):
        response = client.get(f"/scripts/{attempt}")
        assert response.status_code in (404, 405), attempt
        assert "hunter2" not in response.text
        assert "root:" not in response.text


def test_source_is_served_for_a_catalogued_script(client, scripts_dir):
    _write(scripts_dir / "tool.py", "'''Tool.'''\nprint('hello')\n")
    script_id = client.get("/catalog").json()["scripts"][0]["id"]

    body = client.get(f"/scripts/{script_id}/source").json()

    assert "print('hello')" in body["content"]
    assert body["truncated"] is False


def test_source_is_bounded_and_says_so(client, scripts_dir):
    _write(scripts_dir / "big.py", "'''Big.'''\n" + ("# padding\n" * 5000))
    script_id = client.get("/catalog").json()["scripts"][0]["id"]

    body = client.get(f"/scripts/{script_id}/source", params={"max_bytes": 2048}).json()

    assert body["truncated"] is True
    assert body["bytes"] <= 2048


def test_source_of_a_binary_file_is_refused_not_mojibaked(client, scripts_dir):
    """NEGATIVE CONTROL: a .py that is actually a binary must not be decoded
    into the operator's browser."""
    path = scripts_dir / "compiled.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x7fELF\x00\x00\x00\x01binary")
    script_id = client.get("/catalog").json()["scripts"][0]["id"]

    assert client.get(f"/scripts/{script_id}/source").status_code == 415


def test_source_of_a_deleted_script_is_404_not_a_500(client, scripts_dir):
    path = _write(scripts_dir / "gone.py", "'''Gone.'''\n")
    script_id = client.get("/catalog").json()["scripts"][0]["id"]
    path.unlink()

    assert client.get(f"/scripts/{script_id}/source").status_code == 404


def test_a_symlink_to_a_credential_is_never_catalogued_nor_served(client, scripts_dir, tmp_path):
    """NEGATIVE CONTROL — the reported leak, end to end over HTTP.

    ``innocent.py -> .env`` has a catalogued extension, so the closed extension
    list does not stop it. The assertion is on the SECRET appearing anywhere in
    the responses, not merely on the entry count, so a build that leaks cannot
    pass by keeping the name out of the list.
    """
    secret = tmp_path / "hermes" / ".env"
    secret.write_text("SECRET_TOKEN=hunter2\n", encoding="utf-8")
    (scripts_dir).mkdir(parents=True, exist_ok=True)
    (scripts_dir / "innocent.py").symlink_to(secret)

    catalog = client.get("/catalog", params={"refresh": "true"}).json()

    assert catalog["scripts"] == []
    assert "hunter2" not in client.get("/catalog").text


def test_source_is_refused_when_the_file_became_a_symlink_after_the_scan(client, scripts_dir, tmp_path):
    """The scan-time check alone loses the race: /source reads later.

    Only O_NOFOLLOW at read time closes the window; without it this returns the
    credential with a 200.
    """
    secret = tmp_path / "hermes" / ".env"
    secret.write_text("SECRET_TOKEN=hunter2\n", encoding="utf-8")
    path = _write(scripts_dir / "tool.py", "'''Tool.'''\n")
    script_id = client.get("/catalog").json()["scripts"][0]["id"]

    path.unlink()
    path.symlink_to(secret)

    response = client.get(f"/scripts/{script_id}/source")

    assert response.status_code == 404
    assert "hunter2" not in response.text


def test_source_still_works_for_an_ordinary_file(client, scripts_dir):
    """POSITIVE CONTROL for the two refusals above: a reader that refuses
    everything would pass both negatives and break the feature."""
    _write(scripts_dir / "ok.py", "'''Ok.'''\nprint('served')\n")
    script_id = client.get("/catalog").json()["scripts"][0]["id"]

    body = client.get(f"/scripts/{script_id}/source").json()

    assert "print('served')" in body["content"]


# --- Surface shape ----------------------------------------------------------


def test_the_surface_is_read_only_by_construction(plugin):
    """No route on this router accepts a writing method.

    Asserted over the route table rather than by probing one path, so a future
    POST cannot be added without this failing.
    """
    methods = {method for route in plugin.router.routes for method in getattr(route, "methods", set())}

    assert methods <= {"GET", "HEAD"}, f"scripts library must stay read-only, found {methods}"


def test_no_route_executes_a_script(client, scripts_dir, tmp_path):
    """NEGATIVE CONTROL — execution. The card asked for read-only access.

    The catalogued script writes a sentinel if it ever runs; every route is
    exercised and the sentinel must still not exist.
    """
    sentinel = tmp_path / "EXECUTED"
    _write(
        scripts_dir / "sideeffect.py",
        f'"""Has a side effect."""\nfrom pathlib import Path\nPath({str(sentinel)!r}).write_text("ran")\n',
        mode=0o755,
    )
    script_id = client.get("/catalog").json()["scripts"][0]["id"]

    client.get(f"/scripts/{script_id}")
    client.get(f"/scripts/{script_id}/source")
    client.get("/health")

    assert not sentinel.exists(), "a catalogue route executed the catalogued script"


def test_health_distinguishes_nothing_configured_from_a_broken_scan(client, scripts_dir):
    empty = client.get("/health").json()
    assert empty["ok"] is True
    assert empty["scripts"] == 0

    _write(scripts_dir / "tool.py", "'''Tool.'''\n")
    # `refresh` is what makes this an assertion instead of a coin flip: reading
    # through the TTL cache could legitimately answer 0 OR 1, and a test that
    # accepts both measures nothing.
    client.get("/catalog", params={"refresh": "true"})
    assert client.get("/health").json()["scripts"] == 1


def test_refresh_bypasses_the_cache_so_a_new_script_appears(client, scripts_dir):
    _write(scripts_dir / "first.py", "'''First.'''\n")
    assert client.get("/catalog").json()["total"] == 1

    _write(scripts_dir / "second.py", "'''Second.'''\n")

    # Without refresh the short TTL cache may still answer 1; with refresh the
    # answer must be current.
    assert client.get("/catalog", params={"refresh": "true"}).json()["total"] == 2


def test_manifest_declares_the_backend_and_a_hidden_tab(plugin):
    """The manifest is what makes the dashboard mount the API at all.

    Also pins ``hidden``: the dashboard reaches this plugin from the Plugins
    hub, while the desktop contributes its own sidebar entry — a second
    always-on tab would double the UI.
    """
    import json

    manifest = json.loads((PLUGIN_API.parent / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["name"] == "scripts-library"
    assert manifest["api"] == "plugin_api.py"
    assert manifest["tab"]["hidden"] is True
