from pathlib import Path

import toml


def toml_plan_name(path: str) -> str:
    """
    Extract Plan Name from an OWL TOML file.

    Expected TOML structure:
      [Basic Info]
      Plan Name = "Jack & Jill"
    """
    p = Path(path)

    if not p.exists():
        raise FileNotFoundError(f"TOML file not found: {p}")

    data = toml.load(p)

    try:
        name = data["Plan Name"]
    except KeyError as e:
        raise KeyError(f"'Plan Name' not found in section of {p}") from e

    # Normalize for filesystem safety
    return name.strip().replace(" ", "_").replace("&", "and")
