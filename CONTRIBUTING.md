# Contributing

Thanks for contributing to CodeHelm.

## Setup

```powershell
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -e .
```

## Development Rules

- Keep changes focused and small.
- Add or update tests for behavior changes.
- Keep CLI and API behavior consistent when possible.
- Update `README.md` when user-facing commands or flags change.

## Run Tests

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

## Pull Request Checklist

- [ ] Tests pass locally.
- [ ] New behavior has test coverage.
- [ ] Docs are updated.
- [ ] No secrets or local machine paths are committed.
