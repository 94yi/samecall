"""Optional, explicit metadata on the example's ordinary Python signatures."""
from dataclasses import dataclass


@dataclass(frozen=True)
class FieldID:
    value: str


@dataclass(frozen=True)
class RenamedFrom:
    value: str
