from pathlib import Path
from typing import Iterable
import yaml
import tomllib
import click
from loguru import logger


# ---------------------------------------------------------------------
# Config discovery utilities (Hydra-free)
# ---------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    """
    Load YAML file safely.
    Returns empty dict if file is missing or empty.
    """
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text())
    return data or {}


def find_default_groups(conf_dir: Path) -> list[str]:
    """
    Read conf/config.yaml and return config groups declared in defaults.

    Ignores Hydra internals and override entries.
    """
    config_yaml = conf_dir / "config.yaml"
    data = _load_yaml(config_yaml)

    groups: list[str] = []

    for entry in data.get("defaults", []):
        if isinstance(entry, dict):
            for key in entry.keys():
                # Ignore Hydra internal defaults
                if key.startswith("hydra/"):
                    continue
                if key.startswith("override "):
                    continue
                groups.append(key)

    return groups


def _extract_leaf_paths(data, prefix="") -> list[str]:
    """
    Recursively extract dotted leaf paths from nested dicts.
    """
    paths: list[str] = []

    if isinstance(data, dict):
        for key, value in data.items():
            full = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                paths.extend(_extract_leaf_paths(value, full))
            else:
                paths.append(full)

    return paths

def extract_leaf_paths_with_values(data, prefix=""):
    """
    Recursively extract (path, value) pairs from nested dicts.

    Only leaf values are returned.
    """
    results: list[tuple[str, object]] = []

    if isinstance(data, dict):
        for key, value in data.items():
            # key may contain spaces – that is fine
            full_key = f"{prefix}.{key}" if prefix else key

            if isinstance(value, dict):
                results.extend(
                    extract_leaf_paths_with_values(value, full_key)
                )
            else:
                results.append((full_key, value))

    return results

def list_group_override_paths(conf_dir: Path, group: str) -> list[str]:
    """
    Return leaf override paths for a config group based on default.yaml.

    Example:
      solver → ["solver.netSpending", "solver.maxBequest"]
    """
    path = conf_dir / group / "default.yaml"
    schema = _load_yaml(path)

    if not schema:
        return []

    return _extract_leaf_paths(schema)


def list_override_paths(
    conf_dir: Path,
    groups: Iterable[str] | None = None,
) -> dict[str, list[str]]:
    """
    Return mapping of group → override paths.

    If groups is None, uses groups declared in config.yaml defaults.
    """
    if groups is None:
        groups = find_default_groups(conf_dir)

    overrides: dict[str, list[str]] = {}

    for group in groups:
        paths = list_group_override_paths(conf_dir, group)
        if paths:
            overrides[group] = paths

    return overrides

def list_group_override_items(
    conf_dir: Path,
    group: str,
) -> list[tuple[str, object]]:
    """
    Return (path, value) pairs for a config group based on default.yaml.

    Example:
      solver → [("solver.netSpending", 0), ("solver.maxBequest", 0)]
    """
    path = conf_dir / group / "default.yaml"
    schema = _load_yaml(path)

    if not schema:
        return []

    return extract_leaf_paths_with_values(schema)

def list_override_items(
    conf_dir: Path,
    groups: Iterable[str] | None = None,
) -> dict[str, list[tuple[str, object]]]:
    """
    Return mapping of group → list of (path, default_value).

    If groups is None, uses groups declared in config.yaml defaults.
    """
    if groups is None:
        groups = find_default_groups(conf_dir)

    overrides: dict[str, list[tuple[str, object]]] = {}

    for group in groups:
        items = list_group_override_items(conf_dir, group)
        if items:
            overrides[group] = items

    return overrides


def format_override_help(
    conf_dir: Path,
    groups: Iterable[str] | None = None,
    max_items: int = 10,
) -> str:
    """
    Format override paths for inclusion in CLI --help output.

    Limits number of items per group for readability.
    """
    overrides = list_override_items(conf_dir, groups)

    if not overrides:
        return ""

    lines = ["\nExamples of possible overrides:\n"]
    for group, paths in overrides.items():
        for path, value in paths:
            lines.append(f"  {group}.{path}={value}")

    return "\n".join(lines) + "\n"


def format_click_options(cmd: click.Command) -> str:
    """
    Format Click options for inclusion in custom help output.
    """
    lines = []
    for param in cmd.params:
        if not isinstance(param, click.Option):
            continue

        opts = ", ".join(param.opts)
        help_text = param.help or ""

        lines.append(f"  {opts:<15} {help_text}")

    if len(lines) == 0:
        return ""
    
    lines.insert(0, "\nOptions:\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------
# Case discovery & indexing
# ---------------------------------------------------------------------

def find_case_files(directory: Path) -> list[Path]:
    """Return sorted list of .toml case files."""
    return sorted(directory.glob("*.toml"))


def index_case_files(files: list[Path]) -> list[tuple[int, Path]]:
    """Assign stable integer IDs to case files."""
    return list(enumerate(files))


# ---------------------------------------------------------------------
# Selector resolution
# ---------------------------------------------------------------------

def resolve_case_selector(
    selector: str,
    indexed_files: list[tuple[int, Path]],
) -> Path | None:
    """
    Resolve a selector into a case Path.

    Selector may be:
      - integer ID
      - filename
      - filename stem
    """
    # Integer ID
    if selector.isdigit():
        idx = int(selector)
        return next((f for i, f in indexed_files if i == idx), None)

    # Filename or stem
    path = Path(selector)
    if not path.suffix:
        path = path.with_suffix(".toml")

    return next(
        (f for _, f in indexed_files if f.name == path.name),
        None,
    )


# ---------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------

def load_case_metadata(path: Path) -> dict:
    """Load TOML safely; return empty dict on failure."""
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except Exception as e:
        logger.warning(f"Failed to load {path}: {e}")
        return {}


def format_optimization_summary(data: dict) -> str:
    opt_block = data.get("Optimization Parameters", {})
    solver_opts = data.get("Solver Options", {})

    objective = opt_block.get("Objective", "")

    if objective == "maxSpending":
        target = solver_opts.get("bequest")
        return f"maxSpending (bequest={target})" if target is not None else "maxSpending"

    if objective == "maxBequest":
        target = solver_opts.get("netSpending")
        return f"maxBequest (netSpending={target})" if target is not None else "maxBequest"

    return objective or ""


def print_case_list(directory: Path) -> list[Path]:
    """
    Print the standard case list and return the ordered case files.
    Used by both `roost cases` and `roost run`.
    """
    files = find_case_files(directory)

    if not files:
        click.echo("No .toml case files found.")
        return []

    indexed = index_case_files(files)

    click.echo(
        f"{'ID':>3} "
        f"{'FILE':<30} "
        f"{'CASE NAME':<20} "
        f"{'HFP FILE':<25} "
        f"{'OPTIMIZATION':<25}"
    )
    click.echo("-" * 115)

    for idx, path in indexed:
        data = load_case_metadata(path)

        case_name = data.get("Plan Name", "")
        if len(case_name) > 20:
            case_name = case_name[:16] + "..."

        hfp_name = data.get("Household Financial Profile", {}).get(
            "HFP file name", ""
        )

        opt_display = format_optimization_summary(data)

        click.echo(
            f"{idx:>3} "
            f"{path.stem:<30} "
            f"{case_name:<20} "
            f"{hfp_name:<25} "
            f"{opt_display:<25}"
        )

    return files


def normalize_case_file_overrides(args: Iterable[str]) -> list[str]:
    """
    Replace any case.file=<path> with case.file=<filename>.

    Example:
      case.file=/a/b/Case_x.toml → case.file=Case_x.toml
    """
    normalized: list[str] = []

    for arg in args:
        if arg.startswith("case.file="):
            _, value = arg.split("=", 1)
            filename = Path(value).name
            normalized.append(f"case.file={filename}")
        else:
            normalized.append(arg)

    return normalized
