"""Resolve explicit field identities; a missing declaration is not a constraint."""
from call_plan import INPUTS


def constraints(legacy_ids, entry, targets):
    if not isinstance(legacy_ids, dict) or legacy_ids.keys() != set(INPUTS):
        raise ValueError("legacy_ids must identify all three legacy fields")
    if any(not isinstance(v, str) or not v for v in legacy_ids.values()):
        raise ValueError("field IDs must be nonempty strings")
    by_id = {v: k for k, v in legacy_ids.items()}
    if len(by_id) != len(INPUTS):
        raise ValueError("duplicate legacy field ID")
    if not isinstance(entry, dict) or entry.keys() - {"ids", "renamed_from"}:
        raise ValueError("invalid method catalog entry")
    ids, renames = entry.get("ids", {}), entry.get("renamed_from", {})
    for group in (ids, renames):
        if not isinstance(group, dict) or group.keys() - targets:
            raise ValueError("catalog refers to an unknown parameter")
        if any(not isinstance(v, str) or not v for v in group.values()):
            raise ValueError("invalid parameter declaration")
    if len(set(ids.values())) != len(ids):
        raise ValueError("duplicate target field ID")
    # None means a declared new identity, not an undocumented parameter.
    bindings = {name: by_id.get(identity) for name, identity in ids.items()}
    for name, source in renames.items():
        if source not in INPUTS or (name in bindings and bindings[name] != source):
            raise ValueError("conflicting rename or unknown legacy field")
        bindings[name] = source
    fixed = [v for v in bindings.values() if v is not None]
    if len(set(fixed)) != len(fixed):
        raise ValueError("two parameters claim the same legacy field")
    return bindings
