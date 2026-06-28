from brainpalace_cli.commands import init as init_mod


def test_preview_merged_overlays_detected_provider(monkeypatch, tmp_path):
    monkeypatch.setattr(
        init_mod, "_preview_embedding", lambda root: ("cohere", "embed-v4")
    )
    monkeypatch.setattr(
        "brainpalace_server.config.provider_config.load_merged_config_dict",
        lambda *a, **k: {"reranker": {"enabled": False}},
    )
    merged = init_mod._preview_merged_config(tmp_path)
    assert merged["embedding"]["provider"] == "cohere"
    assert merged["embedding"]["model"] == "embed-v4"
    assert merged["reranker"]["enabled"] is False  # untouched keys preserved
