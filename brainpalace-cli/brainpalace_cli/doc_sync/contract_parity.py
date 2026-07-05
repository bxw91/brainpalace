"""Generic cross-surface parity gate.

A *contract* is one canonical token set (the source of truth) plus a set of named
*surfaces* that each independently re-declare that set. The check asserts every
surface equals the SoT, in BOTH directions (a surface missing a token, or carrying
an extra one), and fails loud per surface (an extractor that raises is reported by
name, never crashes the run). Register a contract once; `check_all` loops them all.
This kills the "same list hardcoded in N places drifts apart" bug class for any
future contract, not just query modes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Contract:
    name: str
    sot: Callable[[], set[str]]
    surfaces: dict[str, Callable[[], set[str]]] = field(default_factory=dict)


@dataclass(frozen=True)
class ParityMismatch:
    contract: str
    surface: str
    missing: frozenset[str] = frozenset()  # in SoT, absent from the surface
    extra: frozenset[str] = frozenset()  # in the surface, absent from the SoT
    error: str | None = None  # the extractor (or SoT) raised


_CONTRACTS: dict[str, Contract] = {}


def register_contract(
    name: str,
    sot: Callable[[], set[str]],
    surfaces: dict[str, Callable[[], set[str]]],
) -> None:
    _CONTRACTS[name] = Contract(name, sot, dict(surfaces))


def clear_contracts() -> None:
    _CONTRACTS.clear()


def check_contract(name: str) -> list[ParityMismatch]:
    c = _CONTRACTS[name]
    try:
        truth = c.sot()
    except Exception as exc:  # noqa: BLE001 - report, don't crash the gate
        return [ParityMismatch(c.name, "<sot>", error=repr(exc))]
    out: list[ParityMismatch] = []
    for surface, extract in c.surfaces.items():
        try:
            got = extract()
        except Exception as exc:  # noqa: BLE001
            out.append(ParityMismatch(c.name, surface, error=repr(exc)))
            continue
        missing = frozenset(truth - got)
        extra = frozenset(got - truth)
        if missing or extra:
            out.append(ParityMismatch(c.name, surface, missing=missing, extra=extra))
    return out


def check_all() -> list[ParityMismatch]:
    out: list[ParityMismatch] = []
    for name in _CONTRACTS:
        out.extend(check_contract(name))
    return out


def format_mismatches(mismatches: list[ParityMismatch]) -> str:
    if not mismatches:
        return "contract parity OK"
    lines = ["contract parity FAILED:"]
    for m in mismatches:
        if m.error is not None:
            lines.append(f"  [{m.contract}] {m.surface}: extractor error: {m.error}")
        else:
            lines.append(
                f"  [{m.contract}] {m.surface}: "
                f"missing={sorted(m.missing)} extra={sorted(m.extra)}"
            )
    return "\n".join(lines)
