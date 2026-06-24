from brainpalace_server.models import domains


def test_builtin_domains_present():
    assert {"code", "chat-life"} <= domains.known_domains()


def test_register_adds_domain_without_editing_source():
    assert not domains.is_known_domain("glasses")
    domains.register_domain("glasses")
    assert domains.is_known_domain("glasses")


def test_default_domain():
    assert domains.DEFAULT_DOMAIN == "code"
