# Test Directory Guidelines for Claude Code

This directory contains tests for brainpalace-cli.

## Test Commands

```bash
# Run all tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=brainpalace_cli --cov-report=term-missing

# Run specific test file
poetry run pytest tests/test_commands.py -v

# Run with verbose output
poetry run pytest -v --tb=short
```

## CLI Testing Pattern

```python
from click.testing import CliRunner
from brainpalace_cli.cli import cli

def test_status_command():
    runner = CliRunner()
    result = runner.invoke(cli, ['status'])
    assert result.exit_code == 0
```

## Quality Standards

Before committing test changes:
- [ ] All tests pass (`poetry run pytest`)
- [ ] Coverage >= 50% for new code
- [ ] HTTP calls are properly mocked
- [ ] CLI commands tested with `CliRunner`
