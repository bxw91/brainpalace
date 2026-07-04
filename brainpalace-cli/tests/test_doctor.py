"""`brainpalace doctor` — LSP install offer."""

from click.testing import CliRunner

from brainpalace_cli.cli import cli
from brainpalace_cli.diagnostics import DoctorReport
from brainpalace_cli.lsp_install import EnsureResult


def _healthy_report(tmp_path) -> DoctorReport:
    # All-OK report => exit_code 0, so the test asserts the LSP offer behaviour
    # deterministically rather than coupling to the live environment's health.
    return DoctorReport(
        project_root=str(tmp_path),
        state_dir=str(tmp_path / ".brainpalace"),
        state_dir_exists=True,
        runtime_file=None,
        server_url="http://127.0.0.1:8000",
        checks=[],
    )


def test_doctor_offers_lsp_install_when_missing(monkeypatch, tmp_path):
    import brainpalace_cli.commands.doctor as doc

    monkeypatch.setattr(doc, "run_doctor", lambda **k: _healthy_report(tmp_path))
    # Force "python configured but server missing".
    monkeypatch.setattr(
        doc, "_lsp_missing_languages", lambda: ["python"], raising=False
    )
    called = {}

    def _ensure(lang, **k):
        called["lang"] = lang
        return EnsureResult.INSTALLED

    monkeypatch.setattr(doc, "ensure_server", _ensure, raising=False)
    r = CliRunner().invoke(cli, ["doctor", "--yes"])
    assert called.get("lang") == "python"
    assert r.exit_code == 0, r.output
