"""Language-server-protocol cross-reference subsystem (Phase 150).

Opt-in, per-language. Produces a typed symbol graph (calls / references / type
hierarchy) from real language servers. Inert unless BRAINPALACE_LSP_LANGUAGES is
set; fail-soft when a server binary is missing.
"""
