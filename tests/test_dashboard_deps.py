"""Tests for the dashboard's optional-dependency handling.

The TUI dashboard (`core/dashboard.py`) needs `textual` and `rich`. The core
engine is stdlib-only, so those ship as the `dashboard` extra
(`pip install weft[dashboard]`). These tests pin that contract: the extra is
declared, importing the module never hard-fails on a clean install, and
launching without the deps gives an actionable error.
"""

import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).parent.parent

# tomllib is stdlib on 3.11+; the repo supports 3.10+, so fall back to a text
# parse when it's unavailable. (dev extra has no tomli to lean on.)
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only on Python 3.10
    tomllib = None


def _pyproject_text() -> str:
    return (PLUGIN_ROOT / "pyproject.toml").read_text()


# --- frame / packaging: the extra is declared with both libraries ---
class TestDashboardExtraDeclared:
    def _optional_deps(self) -> dict | None:
        if tomllib is None:
            return None
        data = tomllib.loads(_pyproject_text())
        return data["project"].get("optional-dependencies", {})

    def test_dashboard_extra_exists(self):
        deps = self._optional_deps()
        if deps is None:
            assert "dashboard = [" in _pyproject_text()
        else:
            assert "dashboard" in deps, (
                "pyproject.toml must declare a [dashboard] extra so the "
                "dashboard's third-party deps install via pip install weft[dashboard]"
            )

    def test_dashboard_extra_declares_textual_and_rich(self):
        deps = self._optional_deps()
        if deps is None:
            blob = _pyproject_text().lower()
            assert "dashboard = [" in blob
        else:
            blob = " ".join(deps.get("dashboard", [])).lower()
        assert "textual" in blob
        assert "rich" in blob

    def test_core_dependencies_stay_empty(self):
        # The engine must remain stdlib-only; third-party deps belong in extras.
        deps = self._optional_deps()
        if deps is None:
            assert "dependencies = []" in _pyproject_text()
        else:
            data = tomllib.loads(_pyproject_text())
            assert data["project"]["dependencies"] == []


# --- frame: the module imports even when textual/rich are absent (regression) ---
class TestDashboardImportIsSoft:
    def test_module_imports_without_hard_failure(self):
        # Previously `import core.dashboard` raised ModuleNotFoundError on a clean
        # install (textual/rich at module top level). It must now import and merely
        # record the missing dep.
        sys.modules.pop("core.dashboard", None)
        import core.dashboard as dash

        assert hasattr(dash, "WeftDashboard")
        assert hasattr(dash, "_MISSING_DEP")


# --- functional: launching without deps fails with a helpful message ---
class TestImportGuard:
    def test_require_deps_raises_helpful_message(self, monkeypatch):
        import core.dashboard as dash

        # Simulate the deps being absent regardless of what's installed locally.
        monkeypatch.setattr(dash, "_MISSING_DEP", "textual")
        with pytest.raises(SystemExit) as exc:
            dash._require_deps()
        assert "pip install weft[dashboard]" in str(exc.value)

    def test_require_deps_noop_when_present(self, monkeypatch):
        import core.dashboard as dash

        monkeypatch.setattr(dash, "_MISSING_DEP", None)
        dash._require_deps()  # must not raise

    def test_constructing_dashboard_without_deps_is_guarded(self, monkeypatch):
        import core.dashboard as dash

        monkeypatch.setattr(dash, "_MISSING_DEP", "textual")
        with pytest.raises(SystemExit) as exc:
            dash.WeftDashboard()
        assert "pip install weft[dashboard]" in str(exc.value)
