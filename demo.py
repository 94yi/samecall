"""Discover a compatible method, then publish locally only after the artifact passes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipapp

from check_route import check
from call_plan import adapted, plans_for
from service import DeskV1, DeskV3

HERE = Path(__file__).resolve().parent


def trial(factory, method):
    with tempfile.TemporaryDirectory() as root:
        return check(factory, method, Path(root))


def select_plan(factory):
    passed, attempts = [], []
    for name, function in sorted(vars(factory).items()):
        if not name.startswith("dispatch") or not callable(function):
            continue
        matches = []
        for plan in plans_for(name, function):
            try:
                trial(adapted(factory, plan), "dispatch")
            except (ValueError, TypeError):
                continue
            matches.append(plan)
        passed.extend(matches)
        attempts.append((name, "matched" if matches else "rejected"))
    if len(passed) != 1:
        raise ValueError(f"expected one receipt-confirmed call plan, found {len(passed)}")
    return passed[0], attempts


def select(factory):
    plan, attempts = select_plan(factory)
    return plan.method, attempts


def build(directory):
    baseline = trial(DeskV1, "dispatch")
    plan, attempts = select_plan(DeskV3)
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
    return dict(removed="dispatch", attempts=attempts, binding=dict(positional=plan.positional,
                keywords=dict(plan.keywords)), packaged=packaged, artifact=str(final))


if __name__ == "__main__":
    print(json.dumps(build(HERE / "build"), indent=2))
