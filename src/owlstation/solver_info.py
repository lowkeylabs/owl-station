from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, distribution, version
from typing import NamedTuple


class OwlSolverInfo(NamedTuple):
    version: str
    commit: str | None


def _get_vcs_commit(dist_name: str) -> str | None:
    """
    Extract exact VCS commit hash from PEP 610 direct_url.json metadata.
    Returns None if not available (e.g., wheel install).
    """
    try:
        dist = distribution(dist_name)
    except PackageNotFoundError:
        return None

    try:
        direct_url = dist.read_text("direct_url.json")
        if not direct_url:
            return None

        data = json.loads(direct_url)
        vcs_info = data.get("vcs_info", {})
        return vcs_info.get("commit_id")
    except Exception:
        return None


def get_owl_solver_info() -> OwlSolverInfo:
    """
    Return OWL solver version and exact git commit hash (if available).
    """
    try:
        owl_version = version("owlplanner")
    except PackageNotFoundError:
        return OwlSolverInfo(version="unknown", commit=None)

    commit = _get_vcs_commit("owlplanner")
    if commit:
        commit = commit[:7]

    return OwlSolverInfo(version=owl_version, commit=commit)
