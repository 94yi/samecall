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

from catalog import constraints, extract_catalog, methods_of
from check_route import check
from call_plan import adapted, plans_for
from service import DeskV1, CurrentDesk, PlainDesk, PlainLegacy
from examples import old_example, new_example
from source_evidence import sample_filter

HERE = Path(__file__).resolve().parent


def trial(factory, method):
    with tempfile.TemporaryDirectory() as root:
        return check(factory, method, Path(root))


DEFAULT_LIMIT = 64


def discover(factory, catalog=None, max_trials=DEFAULT_LIMIT, compatible=None):
    if type(max_trials) is not int or max_trials < 0:
        raise ValueError("max_trials must be a nonnegative integer")
    methods = methods_of(factory)
    rules, exclusions = {}, {}
    if catalog is not None:
        if not isinstance(catalog, dict) or catalog.keys() != {"methods", "legacy_ids"}:
            raise ValueError("invalid interface catalog")
        entries = catalog["methods"]
        if not isinstance(entries, dict) or entries.keys() - methods.keys():
            raise ValueError("catalog refers to an unknown method")
        for name, function in methods.items():
            targets = set(tuple(inspect.signature(function).parameters)[1:])
            entry = entries.get(name, {})
            legacy_ids = catalog["legacy_ids"]
            rules[name] = constraints(legacy_ids, entry, targets)
            exclusions[name] = {(target, source) for target, tid in entry.get("ids", {}).items()
                                for source, sid in legacy_ids.items() if tid != sid}

    passed, attempts, counts = [], [], {}
    used = 0
    for name, function in sorted(methods.items()):
        matched = False
        counts[name] = 0
        for plan in plans_for(name, function, rules.get(name), exclusions.get(name, ())):
            if compatible is not None and not compatible(plan):
                continue
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
    plan, attempts, _ = discover(factory, extract_catalog(DeskV1, factory),
                                 compatible=sample_filter(DeskV1, factory, old_example))
    return plan, attempts


def select(factory):
    plan, attempts = select_plan(factory)
    return plan.method, attempts


def build(directory, max_trials=DEFAULT_LIMIT, catalog_path=None, plain=False):
    old, current = (PlainLegacy, PlainDesk) if plain else (DeskV1, CurrentDesk)
    baseline = trial(old, "dispatch")
    catalog = (extract_catalog(old, current) if catalog_path is None
               else json.loads(catalog_path.read_text()))
    compatible = sample_filter(old, current, old_example, new_example if plain else None)
    plan, attempts, counts = discover(current, catalog, max_trials, compatible)
    winner = plan.method
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / "parcel-adapter.pyz"
    with tempfile.TemporaryDirectory(dir=directory) as root:
        stage = Path(root) / "package"
        stage.mkdir()
        shutil.copyfile(HERE / "LICENSE", stage / "LICENSE")
        for name in ("service.py", "fields.py", "call_plan.py", "adapter.py", "check_route.py", "runner.py"):
            shutil.copyfile(HERE / name, stage / ("__main__.py" if name == "runner.py" else name))
        edition = "PlainDesk" if plain else "CurrentDesk"
        (stage / "binding.py").write_text(f"from service import {edition} as TargetDesk\nfrom call_plan import CallPlan\nPLAN = {plan!r}\nMETHOD = PLAN.method\n")
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
    parser.add_argument("--plain", action="store_true", help="use editions with no field declarations")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--catalog", action="store_true", help="print extracted declarations only")
    modes.add_argument("--compare", action="store_true", help="compare discovery only, without packaging")
    args = parser.parse_args()
    old, current = (PlainLegacy, PlainDesk) if args.plain else (DeskV1, CurrentDesk)
    if args.catalog:
        report = extract_catalog(old, current)
    elif args.compare:
        catalog = extract_catalog(old, current)
        report = {}
        compatible = sample_filter(old, current, old_example, new_example if args.plain else None)
        modes = [("signature_only", None, None), ("with_catalog", catalog, None)]
        if args.plain:
            modes.append(("direct_only_both_samples", catalog,
                          sample_filter(old, current, old_example, new_example, direct_only=True)))
            modes.append(("source_old_sample", catalog, sample_filter(old, current, old_example)))
        modes.append(("with_source_and_examples", catalog, compatible))
        for label, info, evidence in modes:
            plan, _, counts = discover(current, info, args.max_trials, evidence)
            report[label] = dict(method=plan.method, trials=counts, total=sum(counts.values()))
    else:
        directory = HERE / "build" / "plain" if args.plain else HERE / "build"
        report = build(directory, args.max_trials, plain=args.plain)
    print(json.dumps(report, indent=2))
