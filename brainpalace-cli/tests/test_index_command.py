"""Phase 1.1 — `brainpalace index --watch/--watch-debounce` wire watch_mode."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from brainpalace_cli.commands.index import index_command


def _invoke(args):
    runner = CliRunner()
    with patch("brainpalace_cli.commands.index.DocServeClient") as client_cls:
        inst = client_cls.return_value.__enter__.return_value
        inst.index.return_value = MagicMock(job_id="j1", status="pending", message="")
        inst.estimate_index.return_value = {
            "files": 12,
            "code_files": 8,
            "doc_files": 4,
            "total_bytes": 4096,
            "raw_tokens": 1000,
            "est_embedding_tokens": 1098,
            "overlap_factor": 1.098,
            "tokenizer": "tiktoken:cl100k_base",
            "embedding_provider": "openai",
            "embedding_model": "text-embedding-3-small",
            "summaries_enabled": False,
            "approximate": True,
        }
        result = runner.invoke(index_command, args)
    return result, inst


def test_index_passes_watch_auto(tmp_path):
    result, inst = _invoke([str(tmp_path), "--watch", "auto"])
    assert result.exit_code == 0, result.output
    _, kwargs = inst.index.call_args
    assert kwargs["watch_mode"] == "auto"


def test_index_passes_watch_debounce(tmp_path):
    result, inst = _invoke([str(tmp_path), "--watch", "auto", "--watch-debounce", "7"])
    assert result.exit_code == 0, result.output
    _, kwargs = inst.index.call_args
    assert kwargs["watch_mode"] == "auto"
    assert kwargs["watch_debounce_seconds"] == 7


def test_index_defaults_watch_off(tmp_path):
    result, inst = _invoke([str(tmp_path)])
    assert result.exit_code == 0, result.output
    _, kwargs = inst.index.call_args
    assert kwargs["watch_mode"] is None
    assert kwargs["watch_debounce_seconds"] is None


def test_index_estimate_only_estimates_and_skips_indexing(tmp_path):
    result, inst = _invoke([str(tmp_path), "--estimate"])
    assert result.exit_code == 0, result.output
    inst.estimate_index.assert_called_once()
    inst.index.assert_not_called()
    assert "embedding" in result.output.lower()
    assert "1,098" in result.output  # est_embedding_tokens, comma-formatted


def test_index_estimate_json(tmp_path):
    result, inst = _invoke([str(tmp_path), "--estimate", "--json"])
    assert result.exit_code == 0, result.output
    inst.index.assert_not_called()
    assert '"est_embedding_tokens": 1098' in result.output
