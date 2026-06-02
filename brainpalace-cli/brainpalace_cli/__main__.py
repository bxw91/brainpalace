"""Enable ``python -m brainpalace_cli`` as a fallback to the console script.

Used when the ``brainpalace`` entry point is not on PATH (running from source,
as a module, or an uninstalled dev checkout) so nested subcommands still work.
"""

from brainpalace_cli.cli import cli

if __name__ == "__main__":
    cli()
