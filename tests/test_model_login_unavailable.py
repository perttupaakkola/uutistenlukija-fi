import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from news_mvp import editorial
from news_mvp.editorial import HermesModel, ModelUnavailable, model_login_unavailable
from news_mvp.store import database

# Real stderr text from the 7 Nov 2026 outage (secret-free).
REAL_STDERR = ("RuntimeError: HTTP 401: Claude Code is installed but has no usable login in the "
               "environment Hermes runs it in. Run `claude auth login` as the user Hermes runs as "
               "(native: Failed to authenticate: OAuth session expired and could not be refreshed)")


class ModelLoginUnavailableTest(unittest.TestCase):
    def test_real_outage_text_is_classified(self):
        self.assertTrue(model_login_unavailable(REAL_STDERR))
        self.assertFalse(model_login_unavailable("ValueError: Invalid title"))

    def test_hermes_call_raises_model_unavailable(self):
        done = subprocess.CompletedProcess([], 1, stdout="", stderr=REAL_STDERR)
        with tempfile.TemporaryDirectory() as home, mock.patch.object(editorial.Path, "home", return_value=Path(home)), \
                mock.patch.object(editorial.subprocess, "run", return_value=done):
            profile = Path(home) / ".hermes/profiles/news-mvp"
            profile.mkdir(parents=True)
            (profile / "config.yaml").write_text("x: 1\n")
            with self.assertRaises(ModelUnavailable):
                HermesModel("hermes").call("writer", {"fixture": False, "kind": "news"})

    def test_deferral_refunds_attempt(self):
        with tempfile.TemporaryDirectory() as d:
            with database(d) as store:
                store.db.execute("INSERT INTO jobs (id,story_key,source_url,packet,status,attempts,created_at) "
                                 "VALUES ('j','k','https://x.fi/','{}','running',3,'2026-11-07T11:11:04+00:00')")
                store.db.commit()
                store.defer_model_unavailable("j", 1000.0, 900, "Editorial model login unavailable")
                row = store.get("j")
                self.assertEqual((row["status"], row["attempts"], row["next_attempt"]), ("ready", 2, 1900.0))


if __name__ == "__main__":
    unittest.main()
