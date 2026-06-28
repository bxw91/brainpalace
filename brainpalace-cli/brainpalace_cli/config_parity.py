"""CLI-side config-field parity gate (``lint:config-parity``).

Imports the LIVE registry and asserts it stays complete and safe:

(a) every field of every section model (+ the nested archive) has a spec;
(b) every spec has a valid ``init_role``;
(c) every ``KNOWN_CONSENT_FIELDS`` entry is ``init_role="consent"``;
(d) every secret field is ``hidden``/``consent`` (never plain-promptable);
(e) every ``choice`` field's ``options_ref`` resolves to a non-empty list;
(f) every spec has a valid ``scope`` (``global|project|both``).

The dashboard half (every rendered field is in the registry or allowlisted, and
``GROUP_ORDER == SECTION_ORDER``) lives in the dashboard test env — the CLI must
not import the dashboard.
"""

from __future__ import annotations

import sys

from brainpalace_cli import config_fields as cf

_VALID_ROLES = ("normal", "advanced", "consent", "hidden")
_VALID_SCOPES = ("global", "project", "both")


def check() -> list[str]:
    """Return a list of parity violations (empty == OK)."""
    errors: list[str] = []

    for section, model in cf.SECTION_MODELS.items():
        for fname in model.model_fields:
            dp = f"{section}.{fname}"
            if dp not in cf.FIELD_SPECS:
                errors.append(f"(a) model field has no spec: {dp}")
    for fname in cf.NESTED_MODELS["session_indexing.archive"].model_fields:
        dp = f"session_indexing.archive.{fname}"
        if dp not in cf.FIELD_SPECS:
            errors.append(f"(a) nested archive field has no spec: {dp}")

    for dp, spec in cf.FIELD_SPECS.items():
        if spec.init_role not in _VALID_ROLES:
            errors.append(f"(b) invalid init_role {spec.init_role!r}: {dp}")
        if spec.secret and spec.init_role not in ("hidden", "consent"):
            errors.append(f"(d) secret field is promptable: {dp}")
        if spec.widget == "choice" and spec.options_ref:
            try:
                if not cf.options_for(spec.options_ref):
                    errors.append(f"(e) choice options empty: {dp}")
            except KeyError:
                errors.append(f"(e) choice options_ref unresolved: {dp}")
        if spec.scope not in _VALID_SCOPES:
            errors.append(f"(f) invalid scope {spec.scope!r}: {dp}")

    for dp in cf.KNOWN_CONSENT_FIELDS:
        cspec = cf.FIELD_SPECS.get(dp)
        if cspec is None:
            errors.append(f"(c) KNOWN_CONSENT_FIELDS dotpath missing: {dp}")
        elif cspec.init_role != "consent":
            errors.append(f"(c) KNOWN_CONSENT_FIELDS not consent: {dp}")

    return errors


def main() -> int:
    errors = check()
    if errors:
        print("config-parity FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("config-parity: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
