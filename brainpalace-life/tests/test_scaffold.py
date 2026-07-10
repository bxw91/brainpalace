"""Proves the subpackage installs and its venv imports the package."""


def test_package_importable():
    import brainpalace_life

    assert brainpalace_life.__version__ == "26.7.3"
