from brainpalace_server.lsp import servers


def test_lsp_feature_dict_from_state(monkeypatch):
    # Build the same dict the health route assembles, via the public helper.
    monkeypatch.setattr(
        servers,
        "lsp_state",
        lambda: {
            "mode": "auto",
            "active": ["python"],
            "detected": ["python"],
            "via_env": False,
        },
    )
    from brainpalace_server.api.routers.health import _lsp_feature

    feat = _lsp_feature()
    assert feat["enabled"] is True
    assert feat["mode"] == "auto"
    assert feat["active"] == ["python"]
    assert feat["languages"] == ["python"]  # back-compat alias
    assert feat["detected"] == ["python"]


def test_lsp_feature_disabled_when_inactive(monkeypatch):
    monkeypatch.setattr(
        servers,
        "lsp_state",
        lambda: {"mode": "auto", "active": [], "detected": [], "via_env": False},
    )
    from brainpalace_server.api.routers.health import _lsp_feature

    feat = _lsp_feature()
    assert feat["enabled"] is False
    assert feat["active"] == []
