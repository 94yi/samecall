import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from demo import HERE, build, discover, select, trial
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


class ParameterTest(unittest.TestCase):
    def test_rename_reorder_and_both(self):
        from demo import select_plan
        from service import Desk, DeskV3

        class Renamed(Desk):
            def dispatch(self, chute, ticket, contents):
                return self._deliver(chute, ticket, contents)

        class Reordered(Desk):
            def dispatch(self, parcel, request, lane, /):
                return self._deliver(lane, request, parcel)

        for factory, pos, kw in [
            (Renamed, (), {"chute":"lane","ticket":"request","contents":"parcel"}),
            (Reordered, ("parcel","request","lane"), {}),
            (DeskV3, ("parcel",), {"order_id":"request","chute":"lane"}),
        ]:
            with self.subTest(factory=factory.__name__):
                plan, _ = select_plan(factory)
                self.assertEqual((plan.positional, dict(plan.keywords)), (pos, kw))

    def test_two_mappings_for_one_method_are_ambiguous(self):
        from service import Desk
        class Ambiguous(Desk):
            def dispatch(self, a, b, c):
                # This desk determines the lane by value, accepting two permutations.
                lane, contents = (a,c) if a.startswith("lane-") else (c,a)
                return self._deliver(lane, b, contents)
        with self.assertRaisesRegex(ValueError, "found 2"):
            select(Ambiguous)

    def test_positional_gap_uses_original_default_object(self):
        from demo import select_plan
        from service import Desk
        marker = object()

        class Gap(Desk):
            def dispatch(self, mode=marker, contents=None, /, *, ticket, chute):
                if mode is not marker or contents is None:
                    raise ValueError("wrong default")
                return self._deliver(chute, ticket, contents)

        plan, _ = select_plan(Gap)
        self.assertEqual(plan.positional, (None, "parcel"))

    def test_optional_slot_ambiguity_preserves_package(self):
        from service import Desk

        class Ambiguous(Desk):
            def dispatch(self, lane, request, *, box=None, bag=None):
                return self._deliver(lane, request, box if box is not None else bag)

        with tempfile.TemporaryDirectory() as d:
            path = Path(build(Path(d))["artifact"])
            previous = path.read_bytes()
            catalog = self.empty_method_catalog(Path(d))
            with patch("demo.CurrentDesk", Ambiguous), self.assertRaisesRegex(ValueError, "found 2"):
                build(Path(d), catalog_path=catalog)
            self.assertEqual(path.read_bytes(), previous)

    @staticmethod
    def empty_method_catalog(directory):
        path = directory / "example.json"
        path.write_text(json.dumps({"legacy_ids": {"lane":"L","request":"R","parcel":"P"},
                                    "methods": {}}))
        return path

    def test_limit_after_a_match_preserves_package(self):
        class FirstMatch(DeskV2):
            dispatch_a = DeskV2.dispatch_v2

        with tempfile.TemporaryDirectory() as d:
            path = Path(build(Path(d))["artifact"])
            previous = path.read_bytes()
            catalog = self.empty_method_catalog(Path(d))
            with patch("demo.CurrentDesk", FirstMatch), patch("demo.trial", wraps=trial) as calls:
                with self.assertRaisesRegex(ValueError, "untested mappings"):
                    build(Path(d), max_trials=1, catalog_path=catalog)
                self.assertEqual(calls.call_count, 2)  # baseline plus the successful first mapping
            self.assertEqual(path.read_bytes(), previous)

    def test_catalog_reduces_actual_trials_and_exact_limit_can_succeed(self):
        from service import CurrentDesk
        catalog = json.loads((HERE / "interface_catalog.json").read_text())
        for info, expected in ((None, 18), (catalog, 5)):
            with patch("demo.trial", wraps=trial) as calls:
                plan, _, counts = discover(CurrentDesk, info, expected)
                self.assertEqual((calls.call_count, sum(counts.values())), (expected, expected))
                self.assertEqual(plan.method, "dispatch_v2")
                self.assertEqual(plan.keywords, (("order_id","request"),("chute","lane")))
                self.assertEqual(plan.positional, ("parcel",))

    def test_conflicting_catalog_stops_before_trial(self):
        from service import CurrentDesk
        catalog = json.loads((HERE / "interface_catalog.json").read_text())
        catalog["methods"]["dispatch_v2"]["renamed_from"]["contents"] = "lane"
        with patch("demo.trial") as calls, self.assertRaisesRegex(ValueError, "conflicting"):
            discover(CurrentDesk, catalog)
        calls.assert_not_called()

    def test_unsupported_signatures_are_not_called(self):
        class Other:
            def dispatch_extra(self, a, b, c, d):
                raise AssertionError("unexpected call")
            def dispatch_variadic(self, *args):
                raise AssertionError("unexpected call")
        with self.assertRaisesRegex(ValueError, "found 0"):
            select(Other)


if __name__ == "__main__":
    unittest.main()
