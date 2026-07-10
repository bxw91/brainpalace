from brainpalace_server.config.project_config import ProjectConfig


def test_default_domain_is_code():
    assert ProjectConfig().domain == "code"


def test_domain_configurable():
    assert ProjectConfig(domain="home").domain == "home"
