def hydra_overrides_to_dict(overrides: list[str]) -> dict:
    """
    Convert Hydra override strings into a nested dictionary,
    correctly handling indexed paths like longevity.values.0=99
    """

    def coerce_value(value: str):
        if value.isdigit():
            return int(value)
        try:
            return float(value)
        except ValueError:
            return value

    result = {}

    for item in overrides:
        if "=" not in item:
            continue

        key, raw_value = item.split("=", 1)
        value = coerce_value(raw_value)

        parts = key.split(".")
        if len(parts) < 2:
            continue

        cur = result

        for i, part in enumerate(parts):
            is_last = i == len(parts) - 1
            next_part = parts[i + 1] if not is_last else None

            # ----------------------------
            # Dictionary key
            # ----------------------------
            if not part.isdigit():
                if is_last:
                    cur[part] = value
                else:
                    # decide container type for next level
                    if part not in cur:
                        cur[part] = [] if next_part and next_part.isdigit() else {}
                    cur = cur[part]

            # ----------------------------
            # List index
            # ----------------------------
            else:
                idx = int(part)

                if not isinstance(cur, list):
                    raise RuntimeError(f"Invalid list index at '{key}'")

                while len(cur) <= idx:
                    cur.append(None)

                if is_last:
                    cur[idx] = value
                else:
                    if cur[idx] is None:
                        cur[idx] = [] if next_part and next_part.isdigit() else {}
                    cur = cur[idx]

    return result
