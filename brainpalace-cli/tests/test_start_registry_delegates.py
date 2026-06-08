from unittest.mock import patch

from brainpalace_cli.commands import start


def test_update_registry_calls_server_writer(tmp_path):
    proj = tmp_path / "proj"
    sd = proj / ".brainpalace"
    sd.mkdir(parents=True)
    with patch("brainpalace_server.registry.upsert_entry") as upsert:
        start.update_registry(proj, sd)
    upsert.assert_called_once_with(proj, sd)
