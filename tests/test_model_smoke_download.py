"""Offline checks for pinned HF download selection and missing artifact failures."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import download_smoke_models as download

SHA = "a" * 40


class TestSmokeDownload(unittest.TestCase):
    def run_download(self, latest=False, missing=False, revision=SHA):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".github").mkdir()
            (root / ".github/model-smoke.json").write_text(json.dumps({"repo_id": "org/private", "revision": revision, "folders": ["criminal_v1"]}))
            output = root / "output"

            def snapshot(repo, **kwargs):
                folder = output / "criminal_v1"
                folder.mkdir(parents=True)
                (folder / "meta.json").write_text("{}")
                if not missing:
                    (folder / "model.joblib").write_bytes(b"fixture")

            with mock.patch.object(download, "ROOT", root), mock.patch.object(download, "HfApi") as api, mock.patch.object(download, "snapshot_download", side_effect=snapshot) as fetch, mock.patch.object(sys, "argv", ["download", "--output", str(output)] + (["--latest"] if latest else [])):
                api.return_value.model_info.return_value.sha = "b" * 40
                download.main()
                self.assertEqual(fetch.call_args.kwargs["allow_patterns"], ["criminal_v1/**"])
                expected = "b" * 40 if latest else SHA
                self.assertEqual(fetch.call_args.kwargs["revision"], expected)
                self.assertEqual(json.loads((output / "smoke-revision.json").read_text())["revision"], expected)
                self.assertEqual(api.return_value.model_info.call_count, int(latest))

    def test_pinned_snapshot(self):
        self.run_download()

    def test_latest_is_resolved_before_download(self):
        self.run_download(latest=True)

    def test_missing_weight_fails(self):
        with self.assertRaises(FileNotFoundError):
            self.run_download(missing=True)

    def test_mutable_revision_fails(self):
        with self.assertRaises(ValueError):
            self.run_download(revision="main")
