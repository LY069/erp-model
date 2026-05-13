"""
tests/test_refresh_endpoint.py — Phase 6 Track B smoke test.

Round-trip the /api/auto-refresh GET + POST endpoints using Flask's
built-in test client (no network, no launchctl side effects exercised —
we mode-switch into "cloud" which has no local effects, then restore
"manual"). Also asserts the persistence file is updated on POST.

Run from repo root:
    python -m unittest tests.test_refresh_endpoint
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class RefreshEndpointTest(unittest.TestCase):
    def setUp(self):
        # Redirect REFRESH_MODE_PATH to a temp location so we don't touch
        # the developer's real ~/.erp_model/refresh_mode.json. Patch both
        # config and the already-imported reference in server.
        import config
        import tempfile
        tmp = Path(tempfile.mkdtemp()) / "refresh_mode.json"
        self._patches = [
            patch.object(config, "REFRESH_MODE_PATH", tmp),
        ]
        for p in self._patches:
            p.start()

        # Import server AFTER patching so it picks up the patched path.
        # If server was already imported in this process, reload it.
        import importlib
        import server as server_module
        importlib.reload(server_module)
        self.server = server_module
        self.tmp_path = tmp

        self.client = self.server.app.test_client()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_get_returns_default_manual_when_file_missing(self):
        resp = self.client.get("/api/auto-refresh")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["mode"], "manual")
        self.assertIn("manual", body["modes"])
        self.assertIn("local", body["modes"])
        self.assertIn("cloud", body["modes"])

    def test_post_cloud_round_trips_and_persists(self):
        # Cloud mode has no local side effects (no launchctl), so it's
        # safe to exercise in a unit test.
        resp = self.client.post(
            "/api/auto-refresh",
            data=json.dumps({"mode": "cloud"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["mode"], "cloud")
        # snapshot.yml currently has no cron, so we expect the YAML diff:
        self.assertIn("snapshot_has_cron", body)
        if not body["snapshot_has_cron"]:
            self.assertIn("yaml_diff", body)
            self.assertIn("cron:", body["yaml_diff"])

        # Persisted file should now exist with mode=cloud.
        self.assertTrue(self.tmp_path.exists())
        saved = json.loads(self.tmp_path.read_text())
        self.assertEqual(saved["mode"], "cloud")

        # GET should now report cloud.
        resp2 = self.client.get("/api/auto-refresh")
        self.assertEqual(resp2.get_json()["mode"], "cloud")

    def test_post_rejects_invalid_mode(self):
        resp = self.client.post(
            "/api/auto-refresh",
            data=json.dumps({"mode": "bogus"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("manual", body["error"])  # the valid-modes list is named in the message


if __name__ == "__main__":
    unittest.main()
