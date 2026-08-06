"""Tests for the hand-over package produced by `make_dist.ps1`.

These guard the distributable rather than the running application: a missing
dependency, a module `make_dist.ps1` forgets to copy, or a launcher script that
disappeared all produce an app that fails only on somebody else's PC, long
after the change was made. Checking them here turns that into a test failure.
"""
from __future__ import annotations

import ast
import os
import re
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The root-level modules the running application imports. Kept in sync with the
# `$coreModules` list in make_dist.ps1 by `test_make_dist_copies_every_core_module`.
CORE_MODULES = [
    "ingest.py",
    "storage.py",
    "excel_sync.py",
    "power_automate.py",
    "extract_checklist.py",
    "extract_order_pdf.py",
]

# Import name -> distribution name on PyPI, where they differ.
_IMPORT_TO_DISTRIBUTION = {
    "docx": "python-docx",
}


def _read(*parts: str) -> str:
    with open(os.path.join(PROJECT_ROOT, *parts), "r", encoding="utf-8-sig") as fh:
        return fh.read()


def _top_level_imports(source: str) -> set[str]:
    """Every top-level package name imported by `source`."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def _requirement_names() -> set[str]:
    """Distribution names listed in requirements.txt, lower-cased."""
    names = set()
    for line in _read("requirements.txt").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # "uvicorn[standard]==0.49.0" -> "uvicorn"
        names.add(re.split(r"[\[<>=!;]", line, maxsplit=1)[0].strip().lower())
    return names


# ── The files a recipient needs ──────────────────────────────────────────────

@pytest.mark.parametrize(
    "name", ["install.bat", "start.bat", "requirements.txt", "README_ERIC.txt", "make_dist.ps1"]
)
def test_handover_file_exists(name):
    assert os.path.isfile(os.path.join(PROJECT_ROOT, name)), (
        f"{name} is required to build the hand-over folder"
    )


# ── requirements.txt really covers what the app imports ──────────────────────

def test_requirements_cover_every_third_party_import():
    """Every third-party package the shipped code imports must be pinned.

    Without this, `install.bat` produces a virtual environment that is missing
    a package and the app dies on first use with an ImportError.
    """
    sources = list(CORE_MODULES) + [
        os.path.join("webapp", "backend", "app.py"),
        os.path.join("webapp", "backend", "derive.py"),
        os.path.join("webapp", "backend", "settings.py"),
    ]

    imported: set[str] = set()
    for rel in sources:
        imported |= _top_level_imports(_read(*rel.split(os.sep)))

    local_modules = {os.path.splitext(m)[0] for m in CORE_MODULES} | {"webapp"}
    third_party = {
        name
        for name in imported
        if name not in sys.stdlib_module_names
        and name not in local_modules
        and not name.startswith("_")
    }

    required = _requirement_names()
    missing = {
        name for name in third_party
        if _IMPORT_TO_DISTRIBUTION.get(name, name).lower() not in required
    }
    assert not missing, f"not listed in requirements.txt: {sorted(missing)}"


def test_requirements_are_pinned():
    """Pinned versions keep a fresh install identical to what was tested."""
    for line in _read("requirements.txt").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            assert "==" in line, f"requirement is not pinned to a version: {line!r}"


# ── make_dist.ps1 ships everything the app needs ─────────────────────────────

def test_make_dist_copies_every_core_module():
    """`make_dist.ps1` must copy each root module the application imports."""
    script = _read("make_dist.ps1")
    for name in CORE_MODULES:
        assert f'"{name}"' in script, f"make_dist.ps1 does not copy {name}"


def test_make_dist_copies_the_launcher_files():
    script = _read("make_dist.ps1")
    for name in ("install.bat", "start.bat", "requirements.txt", "README_ERIC.txt"):
        assert f'"{name}"' in script, f"make_dist.ps1 does not copy {name}"


def test_make_dist_excludes_developer_only_files():
    """The test suite and dev utilities must not land in the hand-over folder."""
    code = "\n".join(
        line for line in _read("make_dist.ps1").splitlines()
        if not line.strip().startswith("#")
    )
    assert "list_sharepoint_folders.py" not in code
    assert '"tests"' not in code


def test_make_dist_ships_the_polling_timeout():
    """The blank config must carry the flow-result timeout.

    Omitting it would silently fall back to the built-in default; shipping it
    explicitly means the recipient can raise it when their OneDrive sync is
    slow, which is the documented remedy for "No shipping date found".
    """
    assert "flow_result_timeout_seconds" in _read("make_dist.ps1")


# ── install.bat / start.bat behaviour the recipient depends on ───────────────

def test_install_bat_uses_requirements_file():
    """The dependency list must have a single source of truth."""
    install = _read("install.bat")
    assert "-r requirements.txt" in install


def test_start_bat_refuses_an_occupied_port():
    """Otherwise start.bat waits for, and opens the browser on, a foreign server."""
    start = _read("start.bat")
    assert "Get-NetTCPConnection" in start
    assert "already in use" in start


def test_start_bat_wait_loop_is_bounded():
    """A crashed server must not leave the recipient waiting forever."""
    start = _read("start.bat")
    assert "lss 60" in start, "start.bat must give up waiting for the server"


# ── the served frontend must not depend on the working directory ─────────────

def test_frontend_is_mounted_from_an_absolute_path():
    """`start.bat` cds into the app folder, but nothing should rely on that.

    Mounting a relative "webapp/frontend/dist" makes the UI 404 whenever the
    server is started from anywhere else.
    """
    app_source = _read("webapp", "backend", "app.py")
    assert 'StaticFiles(directory=DIST_DIR' in app_source
    assert 'StaticFiles(directory="webapp/frontend/dist"' not in app_source

    from webapp.backend import app as app_module

    assert os.path.isabs(app_module.DIST_DIR)
