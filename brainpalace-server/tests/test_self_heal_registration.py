import brainpalace_server.self_heal as sh


def test_base_url_from_scope_ignores_host_header():
    scope = {"server": ("127.0.0.1", 8000), "scheme": "http"}
    host, port, base = sh.address_from_scope(scope, headers_host="evil:9")
    assert (host, port, base) == ("127.0.0.1", 8000, "http://127.0.0.1:8000")


def test_address_falls_back_when_host_unspecified():
    scope = {"server": ("0.0.0.0", 8001), "scheme": "http"}
    host, port, base = sh.address_from_scope(scope, headers_host=None)
    assert host == "127.0.0.1" and port == 8001


def test_register_writes_runtime_and_registry(tmp_path, monkeypatch):
    state_dir = tmp_path / ".brainpalace"
    state_dir.mkdir()
    project_root = tmp_path

    written = {}
    monkeypatch.setattr(
        sh, "write_runtime", lambda sd, rs: written.update(sd=sd, rs=rs)
    )
    upserts = []
    monkeypatch.setattr(
        sh.registry, "upsert_entry", lambda pr, sd: upserts.append((pr, sd))
    )

    sh.register(
        state_dir,
        project_root,
        base_url="http://127.0.0.1:8000",
        bind_host="127.0.0.1",
        port=8000,
    )

    assert written["rs"].base_url == "http://127.0.0.1:8000"
    assert written["rs"].pid > 0
    assert upserts == [(project_root, state_dir)]
