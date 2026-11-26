"""Resolve explicit field identities; a missing declaration is not a constraint."""
import inspect
from typing import Annotated, get_args, get_origin

from call_plan import INPUTS
from fields import FieldID, RenamedFrom


def methods_of(factory):
    return {n: f for n, f in vars(factory).items()
            if n.startswith("dispatch") and inspect.isfunction(f)}


def declarations(function):
    entry = {}
    for field in tuple(inspect.signature(function).parameters.values())[1:]:
        if get_origin(field.annotation) is not Annotated:
            continue
        for tag in get_args(field.annotation)[1:]:
            if not isinstance(tag, (FieldID, RenamedFrom)):
                continue
            group = entry.setdefault("ids" if isinstance(tag, FieldID) else "renamed_from", {})
            if field.name in group and group[field.name] != tag.value:
                raise ValueError(f"conflicting annotations for {field.name}")
            group[field.name] = tag.value
    return entry


def extract_catalog(legacy, current):
    return {"legacy_ids": declarations(legacy.dispatch).get("ids", {}),
            "methods": {name: declarations(fn) for name, fn in methods_of(current).items()}}



def constraints(legacy_ids, entry, targets):
    if not isinstance(legacy_ids, dict) or legacy_ids.keys() - set(INPUTS):
        raise ValueError("unknown legacy field")
    if any(not isinstance(v, str) or not v for v in legacy_ids.values()):
        raise ValueError("field IDs must be nonempty strings")
    by_id = {v: k for k, v in legacy_ids.items()}
    if len(by_id) != len(legacy_ids):
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
    bindings = {name: by_id.get(identity) for name, identity in ids.items()
                if identity in by_id or len(by_id) == len(INPUTS)}
    for name, source in renames.items():
        if (source not in INPUTS or (name in bindings and bindings[name] != source)
                or (name in ids and source in legacy_ids and ids[name] != legacy_ids[source])):
            raise ValueError("conflicting rename or unknown legacy field")
        bindings[name] = source
    fixed = [v for v in bindings.values() if v is not None]
    if len(set(fixed)) != len(fixed):
        raise ValueError("two parameters claim the same legacy field")
    return bindings
