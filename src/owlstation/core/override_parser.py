from collections import defaultdict


def hydra_overrides_to_dict(overrides: list[str]) -> dict:
    """
    Convert Hydra override strings into a nested dictionary.

    Example:
        ["longevity.jack=80", "longevity.jill=90"]

    Returns:
        {
            "longevity": {
                "jack": 80,
                "jill": 90
            }
        }
    """
    result = defaultdict(dict)

    for item in overrides:
        if "=" not in item:
            continue

        key, value = item.split("=", 1)
        parts = key.split(".")

        if len(parts) < 2:
            continue  # ignore non-semantic overrides

        section = parts[0]
        name = parts[1]

        # basic type coercion (Hydra already validated)
        if value.isdigit():
            value = int(value)
        else:
            try:
                value = float(value)
            except ValueError:
                pass

        result[section][name] = value

    return dict(result)
