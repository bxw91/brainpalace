"""Conftest for text_analysis unit tests.

text_analysis tests cover stdlib-only code (re, unicodedata) and have no
singletons to manage. Override the root conftest's autouse reset_singletons
fixture with a no-op to keep these tests lightweight.
"""

import pytest


@pytest.fixture(autouse=True)
def reset_singletons():  # noqa: PT004 — intentional no-op override
    """No-op override: text_analysis tests have no singletons to reset."""
    yield
