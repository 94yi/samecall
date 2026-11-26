"""Discover a compatible method, then publish locally only after the artifact passes."""
import argparse
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipapp

from catalog import constraints
from check_route import check
from call_plan import adapted, plans_for
from service import DeskV1, CurrentDesk

HERE = Path(__file__).resolve().parent


def trial(factory, method):
    with tempfile.TemporaryDirectory() as root:
        return check(factory, method, Path(root))


DEFAULT_LIMIT = 64


def discover(factory, catalog=None, max_trials=DEFAULT_LIMIT):
    if type(max_trials) is not int or max_trials < 0:
        raise ValueError("max_trials must be a nonnegative integer")
    methods = {n: f for n, f in vars(factory).items()
               if n.startswith("dispatch") and inspect.isfunction(f)}
    rules = {}
    if catalog is not None:
        if not isinstance(catalog, dict) or catalog.keys() != {"methods", "legacy_ids"}:
            raise ValueError("invalid interface catalog")
        entries = catalog["methods"]
        if not isinstance(entries, dict) or entries.keys() - methods.keys():
            raise ValueError("catalog refers to an unknown method")
        for name, function in methods.items():
            targets = set(tuple(inspect.signature(function).parameters)[1:])
            rules[name] = constraints(catalog["legacy_ids"], entries.get(name, {}), targets)

    passed, attempts, counts = [], [], {}
    used = 0
    for name, function in sorted(methods.items()):
        matched = False
        counts[name] = 0
        for plan in plans_for(name, function, rules.get(name)):
            if used == max_trials:
                raise ValueError(f"trial limit {max_trials} reached; untested mappings remain")
            used += 1
            counts[name] += 1
            try:
                trial(adapted(factory, plan), "dispatch")
            except (ValueError, TypeError):
                continue
            passed.append(plan)
            matched = True
            if len(passed) == 2:
                raise ValueError("found 2 receipt-confirmed call plans")
        attempts.append((name, "matched" if matched else "rejected"))
    if not passed:
        raise ValueError("expected one receipt-confirmed call plan, found 0")
    return passed[0], attempts, counts


def select_plan(factory):
    plan, attempts, _ = discover(factory)
    return plan, attempts


def select(factory):
    plan, attempts = select_plan(factory)
    return plan.method, attempts


def build(directory, max_trials=DEFAULT_LIMIT, catalog_path=HERE / "interface_catalog.json"):
    baseline = trial(DeskV1, "dispatch")
    catalog = json.loads(catalog_path.read_text())
    plan, attempts, counts = discover(CurrentDesk, catalog, max_trials)
    winner = plan.method
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / "parcel-adapter.pyz"
    with tempfile.TemporaryDirectory(dir=directory) as root:
        stage = Path(root) / "package"
        stage.mkdir()
        shutil.copyfile(HERE / "LICENSE", stage / "LICENSE")
        for name in ("service.py", "call_plan.py", "adapter.py", "check_route.py", "runner.py"):
            shutil.copyfile(HERE / name, stage / ("__main__.py" if name == "runner.py" else name))
        (stage / "binding.py").write_text(f"from call_plan import CallPlan\nPLAN = {plan!r}\nMETHOD = PLAN.method\n")
        artifact = Path(root) / "candidate.pyz"
        zipapp.create_archive(stage, artifact)
        output = subprocess.check_output([sys.executable, "-I", str(artifact.resolve())],
                                        cwd=root, text=True, timeout=10)
        packaged = json.loads(output)
        if packaged != dict(method=winner, **baseline):
            raise ValueError("packaged route does not reproduce the original receipts")
        os.replace(artifact, final)
    return dict(removed="dispatch", attempts=attempts, trials=counts, binding=dict(positional=plan.positional,
                keywords=dict(plan.keywords)), packaged=packaged, artifact=str(final))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-trials", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--compare", action="store_true", help="compare discovery only, without packaging")
    args = parser.parse_args()
    if args.compare:
        catalog = json.loads((HERE / "interface_catalog.json").read_text())
        report = {}
        for label, info in (("signature_only", None), ("with_catalog", catalog)):
            plan, _, counts = discover(CurrentDesk, info, args.max_trials)
            report[label] = dict(method=plan.method, trials=counts, total=sum(counts.values()))
    else:
        report = build(HERE / "build", args.max_trials)
    print(json.dumps(report, indent=2))
