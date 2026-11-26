import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from demo import build, select, trial
from service import DeskV2


class DemoTest(unittest.TestCase):
    def test_wrong_receipts_and_standalone_archive(self):
        with tempfile.TemporaryDirectory() as d:
            result = build(Path(d))
            self.assertEqual(dict(result["attempts"]), {
                "dispatch_preview":"rejected", "dispatch_redirect":"rejected", "dispatch_v2":"matched"})
            output = subprocess.check_output([sys.executable, "-I", result["artifact"]], cwd=d, text=True)
            self.assertEqual(json.loads(output), {"method":"dispatch_v2","receipts":[1,2],
                                                "delivery_count":2,"retry_receipt":1})

    def test_old_entrypoint_keeps_orders_across_processes(self):
        with tempfile.TemporaryDirectory() as d:
            result = build(Path(d))
            cmd = [sys.executable, "-I", result["artifact"], "dispatch", "--db",
                   str(Path(d) / "orders.sqlite"), "green", "sample-7"]
            def submit(parcel):
                return subprocess.run(cmd + [parcel], cwd=d, text=True, capture_output=True)
            first = json.loads(submit("lantern").stdout)
            self.assertEqual(first, {"receipt": 1})
            conflict = submit("clock")
            self.assertNotEqual(conflict.returncode, 0)
            self.assertFalse(conflict.stdout)
            self.assertIn("different contents", conflict.stderr)
            self.assertEqual(json.loads(submit("lantern").stdout), first)

    def test_rejection_cannot_modify_original_order(self):
        class CorruptDesk(DeskV2):
            def dispatch_corrupt(self, lane, request, parcel):
                try:
                    return self._deliver(lane, request, parcel)
                except ValueError:
                    with self.db:
                        self.db.execute("DELETE FROM deliveries WHERE request=?", (request,))
                    raise
        with self.assertRaisesRegex(ValueError, "changed existing deliveries"):
            trial(CorruptDesk, "dispatch_corrupt")

    def test_ambiguous_or_missing_replacement(self):
        class Ambiguous(DeskV2):
            dispatch_a = dispatch_b = DeskV2.dispatch_v2
        for factory in (Ambiguous, object):
            with self.assertRaises(ValueError):
                select(factory)

    def test_failed_packaged_replay_preserves_previous_release(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "parcel-adapter.pyz"
            path.write_bytes(b"previous release")
            with patch("demo.subprocess.check_output", return_value="{}"):
                with self.assertRaises(ValueError):
                    build(Path(d))
            self.assertEqual(path.read_bytes(), b"previous release")
