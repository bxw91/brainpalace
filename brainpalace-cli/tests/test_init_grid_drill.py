import click
from click.testing import CliRunner

from brainpalace_cli import config_review as cr


def _drill(group, merged, stdin):
    edits: dict = {}
    seen: list = []

    @click.command()
    def cmd():
        cr._edit_division(
            group,
            merged=merged,
            edits=edits,
            on_consent=lambda s: seen.append(s.dotpath),
        )

    res = CliRunner().invoke(cmd, [], input=stdin)
    return res, edits, seen


def test_off_gate_short_circuits_subfields():
    # Reranker enabled=N → provider/model/base_url must NOT be asked.
    merged = {"reranker": {"enabled": True, "provider": "sentence-transformers"}}
    res, edits, _ = _drill("reranker", merged, stdin="n\n")
    assert res.exit_code == 0, res.output
    assert edits.get("reranker.enabled") is False
    assert "Provider" not in res.output  # sub-fields skipped


def test_drill_edits_advanced_field():
    # api_key_env (advanced) is now editable from the embedding division.
    merged = {
        "embedding": {
            "provider": "openai",
            "model": "m",
            "api_key_env": "OPENAI_API_KEY",
        }
    }
    # Gate-first order: provider, model, api_key (hidden), api_key_env, base_url,
    # params.
    # Enter past provider/model/api_key, type a new env var, enter past base_url/params.
    res, edits, _ = _drill("embedding", merged, stdin="\n\n\nMY_KEY\n\n\n")
    assert res.exit_code == 0, res.output
    assert edits.get("embedding.api_key_env") == "MY_KEY"


def test_drill_separator_and_saved_line():
    merged = {"reranker": {"enabled": False}}
    res, edits, _ = _drill("reranker", merged, stdin="y\n")
    assert "Reranker" in res.output  # section-name separator
    assert "saved" in res.output.lower()  # compact confirmation
