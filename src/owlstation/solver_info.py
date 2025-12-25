from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import NamedTuple


class OwlSolverInfo(NamedTuple):
    version: str
    commit: str | None


def get_owl_solver_info() -> OwlSolverInfo:
    """
    Return OWL solver version and (if available) git commit hash.
    Works for wheel, git, and editable installs.
    """
    try:
        owl_version = version("owlplanner")
    except PackageNotFoundError:
        return OwlSolverInfo(version="unknown", commit=None)

    # Optional: OWL may expose commit info in the future
    try:
        import owlplanner  # type: ignore[attr-defined]

        commit = getattr(owlplanner, "__git_commit__", None)
    except Exception:
        commit = None

    return OwlSolverInfo(version=owl_version, commit=commit)
