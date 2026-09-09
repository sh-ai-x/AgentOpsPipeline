"""Smoke test — proves the package imports and version is exposed.

This is the red->green regression test for the step-1 scaffold. If the
package fails to import or __version__ is missing, the smoke fails.
"""
from __future__ import annotations

import agentops_workbench


def test_package_imports() -> None:
    assert agentops_workbench is not None


def test_version_is_semver_string() -> None:
    v = agentops_workbench.__version__
    parts = v.split(".")
    assert len(parts) == 3, f"version {v!r} is not MAJOR.MINOR.PATCH"
    for p in parts:
        assert p.isdigit(), f"version segment {p!r} is not numeric"
