#!/usr/bin/env python3
"""Rendered regression guard for four staging-confirmed Final POR defects."""

from __future__ import annotations

import os
import subprocess
import sys

from test_support_app_server import COMMISSIONER_EMAIL
from test_support_s7_harness import ensure_authenticated_app

origin = ensure_authenticated_app(seed_pool_slate=True, action_shape="full")
env = dict(os.environ)
env["FS_TEST_ORIGIN"] = origin
command = ["node", os.path.join("web", "tests", "finalpor_four_failures_browser.mjs")]
root = os.path.dirname(os.path.abspath(__file__))
gm_result = subprocess.run(command, env=env, cwd=root)

commissioner_env = dict(env)
commissioner_env["FS_TEST_AUTH_EMAIL"] = COMMISSIONER_EMAIL
commissioner_env["FS_TEST_EXPECT_COMMISSIONER"] = "1"
commissioner_result = subprocess.run(command, env=commissioner_env, cwd=root)
sys.exit(gm_result.returncode or commissioner_result.returncode)
