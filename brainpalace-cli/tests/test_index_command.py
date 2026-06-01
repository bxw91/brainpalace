"""Phase 1.1 — `brainpalace index --watch/--watch-debounce` wire watch_mode."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from brainpalace_cli.commands.index import index_command


def _invoke(args):
    runner = CliRunner()
    with patch("brainpalace_cli.commands.index.DocServeClient") as client_cls:
        inst = client_cls.return_value.__enter__.return_value
        inst.index.return_value = MagicMock(
            job_id="j1", status="pending", message=""
        )
        result = runner.invoke(index_command, args)
    return result, inst


def test_index_passes_watch_auto(tmp_path):
    result, inst = _invoke([str(tmp_path), "--watch", "auto"])
    assert result.exit_code == 0, result.output
    _, kwargs = inst.index.call_args
    assert kwargs["watch_mode"] == "auto"


def test_index_passes_watch_debounce(tmp_path):
    result, inst = _invoke(
        [str(tmp_path), "--watch", "auto", "--watch-debounce", "7"]
    )
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
