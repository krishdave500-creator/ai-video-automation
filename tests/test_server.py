import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import flask  # noqa: F401
except ImportError:  # server.py is optional
    flask = None


@unittest.skipIf(flask is None, "flask not installed (server.py is optional)")
class ServerAuth(unittest.TestCase):
    def setUp(self):
        os.environ["API_TOKEN"] = "secret-token"
        import importlib, server
        importlib.reload(server)
        self.server = server
        self.c = server.app.test_client()

    def test_requires_token(self):
        self.assertEqual(self.c.post("/run", json={"topic": "x"}).status_code, 401)
        self.assertEqual(self.c.post("/run", json={"topic": "x"}, headers={"X-API-Key": "wrong"}).status_code, 401)

    def test_rejects_flag_like_topic(self):
        r = self.c.post("/run", json={"topic": "--upload", "format": "short"}, headers={"X-API-Key": "secret-token"})
        self.assertEqual(r.status_code, 400)

    def test_runs_with_token(self):
        with mock.patch.object(self.server.subprocess, "run") as run:
            r = self.c.post("/run", json={"topic": "Bridges", "format": "short", "upload": "true", "privacy": "public"}, headers={"X-API-Key": "secret-token"})
        self.assertEqual(r.status_code, 200)
        args = run.call_args.args[0]
        self.assertEqual(args[-4:], ["Bridges", "short", "true", "public"])


if __name__ == "__main__":
    unittest.main()
