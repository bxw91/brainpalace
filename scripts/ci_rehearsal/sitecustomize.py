"""CI-rehearsal import blocker — makes ``brainpalace_dashboard`` unimportable.

The publish / PR-QA gate runs in a server+cli env where the dashboard is NOT
installed (its ``python = ">=3.12"`` marker excludes it from the 3.11 job). A dev
box usually HAS the dashboard installed, so code that imports it directly passes
locally yet fails in CI. This module installs a meta-path finder that raises
``ModuleNotFoundError`` for ``brainpalace_dashboard`` (and submodules), so a dev
box reproduces that absence faithfully.

Loaded automatically (Python imports ``sitecustomize`` at startup) because
``task release:rehearse-ci`` puts this directory on ``PYTHONPATH``. Gated on
``BRAINPALACE_BLOCK_DASHBOARD=1`` so a lingering ``PYTHONPATH`` entry is inert
otherwise. Tests that inject their own stub via ``sys.modules`` are unaffected:
``sys.modules`` is consulted before ``sys.meta_path``.
"""

import os
import sys
from importlib.abc import MetaPathFinder

_BLOCKED = "brainpalace_dashboard"


class _DashboardBlocker(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == _BLOCKED or fullname.startswith(_BLOCKED + "."):
            raise ModuleNotFoundError(
                f"No module named {fullname!r} "
                "(blocked by CI rehearsal: dashboard absent in the server+cli gate)"
            )
        return None  # defer to the normal finders for everything else


if os.environ.get("BRAINPALACE_BLOCK_DASHBOARD") == "1":
    sys.meta_path.insert(0, _DashboardBlocker())
