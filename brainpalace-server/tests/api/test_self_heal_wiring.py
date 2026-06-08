from brainpalace_server.api import main


def test_app_has_registration_middleware():
    # Wiring sets a module flag; the http middleware is also on the stack.
    assert getattr(main, "_self_heal_wired", False) is True
    stack = repr(main.app.user_middleware).lower()
    assert "self_heal" in stack or "_self_heal_registration" in stack
