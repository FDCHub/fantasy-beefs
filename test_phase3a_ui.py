"""Rendered Phase Three A regression guard (requires FS_TEST_ORIGIN)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_phase3a_rendered_contract() -> None:
    origin = os.environ.get("FS_TEST_ORIGIN")
    assert origin, "FS_TEST_ORIGIN is required; the rendered tier may not silently skip"
    root = Path(__file__).resolve().parent
    result = subprocess.run(
        ["node", "web/tests/phase3a_browser.mjs"], cwd=root,
        env={**os.environ, "FS_TEST_ORIGIN": origin}, check=False,
    )
    assert result.returncode == 0
