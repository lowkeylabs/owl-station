from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

OWL_REPO = "https://github.com/mdlacasse/Owl.git"

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
TMP = ROOT / ".tmp_owl"
SRC = TMP / "examples"
DST = ROOT / "examples" / "owlplanner"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, check=True, cwd=cwd)


def get_owl_commit_from_pyproject(pyproject: Path) -> str:
    """
    Extract OWL commit SHA from:
      "owlplanner @ git+https://github.com/mdlacasse/Owl.git@<commit>"
    """
    with pyproject.open("rb") as f:
        data = tomllib.load(f)

    deps = data["project"]["dependencies"]

    for dep in deps:
        if dep.startswith("owlplanner @"):
            # Extract text after the final "@"
            match = re.search(r"@([^@]+)$", dep)
            if not match:
                raise ValueError(f"Could not parse OWL commit from dependency: {dep}")
            return match.group(1)

    raise KeyError("owlplanner dependency not found in pyproject.toml")


def main() -> None:
    owl_commit = get_owl_commit_from_pyproject(PYPROJECT)
    print(f"Using OWL commit from pyproject.toml: {owl_commit}")

    if TMP.exists():
        shutil.rmtree(TMP)

    print("Cloning OWL...")
    run(["git", "clone", "--no-checkout", OWL_REPO, str(TMP)])

    print(f"Checking out OWL commit {owl_commit}...")
    run(["git", "checkout", owl_commit], cwd=TMP)

    print("Syncing examples...")
    if DST.exists():
        shutil.rmtree(DST)

    shutil.copytree(SRC, DST)

    shutil.rmtree(TMP)
    print("Done.")


if __name__ == "__main__":
    main()
