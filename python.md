## Python

This section covers Python rules. It applies whenever the project
contains Python code.

### Baseline

- For standalone scripts, the runtime version is pinned via
  `requires-python` in PEP 723 inline metadata and provisioned by
  `uv`. The newest Python can lack wheels for some dependencies —
  don't force the absolute latest at install time.
- Full type hints on every function signature and module-level
  declaration. Checked statically (see *Python tooling* below).

### Style

- Idiomatic, modern Python. Prefer the standard library where it
  suffices.
- `pathlib.Path` over `os.path` for filesystem work.
- `dataclasses` over hand-rolled `__init__` boilerplate; reach for
  `pydantic` only when validation is part of the contract.
- f-strings for interpolation; never `%` or `.format()`.
- Context managers (`with`) for any resource with a close / release
  lifecycle.
- No bare `except:`. Name the exception, or use `except Exception`
  with a comment explaining why a broad catch is appropriate.
- Early returns to flatten nesting.

### Doc comments

Docstrings on every module, class, and public function. Document the
contract and the why; the type hints already show the shape. Pick a
docstring convention (Google or NumPy style) per project and stay
consistent. Use `Args:` / `Returns:` / `Raises:` where they add real
value.

### Standalone-script metadata (PEP 723)

For single-file scripts, declare dependencies and the required
Python version inline at the top of the file:

```python
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "httpx==0.27.0",
#     "rich==13.7.1",
# ]
# ///
```

Pin exact versions. `uv run` resolves and caches the environment
automatically.

### Python tooling

- **uv** as the runtime, package manager, and virtualenv tool. For
  standalone scripts, `uv run` executes a PEP 723 script directly;
  for project work, `uv` manages the project venv and lockfile.
- **ruff** as the single linter and formatter (replaces black,
  isort, flake8, pylint).
- **mypy** or **pyright** for static type checking — pick one per
  project. Strict mode on new code.
- **pytest** for tests.
