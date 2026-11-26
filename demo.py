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
from service import DeskV1, DeskV2

HERE = Path(__file__).resolve().parent


def trial(factory, method):
    with tempfile.TemporaryDirectory() as root:
        return check(factory, method, Path(root))


def select(factory):
    passed, attempts = [], []
    candidates = sorted(k for k in vars(factory) if k.startswith("dispatch") and callable(getattr(factory, k)))
    for method in candidates:
        try:
            trial(factory, method)
        except (ValueError, TypeError):
            attempts.append((method, "rejected"))
        else:
            passed.append(method)
            attempts.append((method, "matched"))
    if len(passed) != 1:
        raise ValueError(f"expected one receipt-confirmed replacement, found {len(passed)}")
    return passed[0], attempts


def build(directory):
    baseline = trial(DeskV1, "dispatch")
    if hasattr(DeskV2, "dispatch"):
        raise ValueError("demo requires the original method to be absent")
    winner, attempts = select(DeskV2)
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / "parcel-adapter.pyz"
    with tempfile.TemporaryDirectory(dir=directory) as root:
        stage = Path(root) / "package"
        stage.mkdir()
        shutil.copyfile(HERE / "LICENSE", stage / "LICENSE")
        for name in ("service.py", "check_route.py", "runner.py"):
            shutil.copyfile(HERE / name, stage / ("__main__.py" if name == "runner.py" else name))
        (stage / "binding.py").write_text(f"METHOD = {winner!r}\n")
        artifact = Path(root) / "candidate.pyz"
        zipapp.create_archive(stage, artifact)
        output = subprocess.check_output([sys.executable, "-I", str(artifact.resolve())],
                                        cwd=root, text=True, timeout=10)
        packaged = json.loads(output)
        if packaged != dict(method=winner, **baseline):
            raise ValueError("packaged route does not reproduce the original receipts")
        os.replace(artifact, final)
    return dict(removed="dispatch", attempts=attempts, packaged=packaged, artifact=str(final))


if __name__ == "__main__":
    print(json.dumps(build(HERE / "build"), indent=2))
