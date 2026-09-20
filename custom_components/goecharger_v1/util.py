"""Helpers for reading values out of the go-eCharger status object."""

from __future__ import annotations

from typing import Any

StatusData = dict[str, Any]


def get_int(data: StatusData | None, key: str) -> int | None:
    """Return a status value as int, or None if missing/unparsable."""
    if not data or key not in data:
        return None
    try:
        return int(str(data[key]).strip())
    except (TypeError, ValueError):
        return None


def get_float(data: StatusData | None, key: str, scale: float = 1.0) -> float | None:
    """Return a status value as float multiplied by scale."""
    if not data or key not in data:
        return None
    try:
        return float(str(data[key]).strip()) * scale
    except (TypeError, ValueError):
        return None


def get_str(data: StatusData | None, key: str) -> str | None:
    """Return a status value as string."""
    if not data or key not in data:
        return None
    value = data[key]
    return None if value is None else str(value)


def get_array(
    data: StatusData | None, key: str, index: int, scale: float = 1.0
) -> float | None:
    """Return an element of an array value (nrg, tma) multiplied by scale."""
    if not data:
        return None
    values = data.get(key)
    if not isinstance(values, list) or index >= len(values):
        return None
    try:
        return float(values[index]) * scale
    except (TypeError, ValueError):
        return None


def get_nrg(data: StatusData | None, index: int, scale: float = 1.0) -> float | None:
    """Return an element of the nrg sensor array multiplied by scale."""
    return get_array(data, "nrg", index, scale)
