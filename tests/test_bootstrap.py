"""Smoke tests for the bootstrap layout.

These do not import any trading code — they only verify that the repo scaffolding
is intact, so CI is green from day one. Wave 1+ will add real functional tests.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_parses() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "commotiai-forex"
    assert data["project"]["requires-python"].startswith(">=3.12")
    assert "ruff" in data["tool"]
    assert "pytest" in data["tool"]


def test_env_example_has_required_keys() -> None:
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for key in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "MT5_FILES"):
        assert re.search(rf"^{key}=", text, re.MULTILINE), f"missing env template key: {key}"


def test_ci_workflow_pins_ruff() -> None:
    """Guardrail against the signalforge-issue-34 regression.

    If ruff is un-pinned in CI, a newer release can flip on default rules and
    turn CI red overnight on unrelated legacy code. Force explicit version.
    """
    ci_text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    req_text = (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "requirements-dev.txt" in ci_text, "CI must install from pinned requirements-dev.txt"
    assert re.search(r"^ruff==\d", req_text, re.MULTILINE), "ruff must be exact-version pinned in requirements-dev.txt"


def test_agents_md_present() -> None:
    """AGENTS.md is the coordination contract between Claude Code and Cline."""
    assert (REPO_ROOT / "AGENTS.md").is_file()
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Claude Code" in text
    assert "Cline" in text


def test_readme_present() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "commotiai-forex" in text.lower()
    assert "Wave" in text  # migration roadmap section
