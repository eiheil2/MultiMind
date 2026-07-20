# Contributing to MultiMind

First off, thank you for taking the time to contribute! :tada:

MultiMind is a community-driven project, and every contribution — whether it
is a bug report, a feature idea, documentation improvement, or a pull request
— is greatly appreciated.

This document explains how to get involved. By participating, you agree to
abide by our [Code of Conduct](CODE_OF_CONDUCT.md). Please read it carefully.

---

## Table of Contents

- [Reporting Bugs](#reporting-bugs)
- [Requesting Features](#requesting-features)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Code Style](#code-style)
- [Testing Requirements](#testing-requirements)
- [Pull Request Process](#pull-request-process)
- [Commit Message Convention](#commit-message-convention)
- [Releasing](#releasing)

---

## Reporting Bugs

A good bug report helps us reproduce and fix issues quickly. Before opening a
new issue:

1. **Search existing issues** to avoid duplicates.
2. **Update to the latest version** and confirm the bug still exists.
3. **Collect context**: OS, Python version, MultiMind version, and the
   channel topology you were using.

When you open a bug report, please use the **Bug Report** template and
include:

- A clear title and a concise description of the problem.
- The exact steps to reproduce (commands, configuration, inputs).
- The expected behaviour versus what actually happened.
- Relevant logs or stack traces — **redact any secrets, API keys, or
  personal data** before pasting.
- Your environment details (`python --version`, `multimind --version`,
  OS, and installed dependencies).

> If you believe you have found a **security vulnerability**, do not open a
> public issue. Follow the private reporting process described in
> [SECURITY.md](SECURITY.md).

---

## Requesting Features

We welcome feature suggestions that align with MultiMind's mission of
multi-AI collaboration. To request a feature:

1. **Search existing issues** (open and closed) to check whether the idea
   has already been discussed.
2. Open a new issue using the **Feature Request** template.
3. Describe:
   - The problem you are trying to solve and your current workaround.
   - The proposed solution and how it would benefit users.
   - Any alternatives you have considered.
4. Be open to discussion — maintainers may request clarification or suggest
   a different approach before the idea is accepted.

Accepted feature requests will be labelled `feature` and prioritised on the
project roadmap.

---

## Development Setup

MultiMind targets **Python 3.10+**. We recommend using a virtual environment
to keep your local setup clean.

### 1. Clone the repository

```bash
git clone https://github.com/multimind/multimind.git
cd multimind
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # On Windows: .venv\Scripts\activate
```

### 3. Install in editable mode with development dependencies

```bash
pip install --upgrade pip
pip install -e ".[dev]"
```

This installs MultiMind along with `ruff`, `mypy`, `pytest`, `pre-commit`,
and other development tools defined in `pyproject.toml`.

### 4. Install the pre-commit hooks

```bash
pre-commit install
```

Pre-commit will automatically run `ruff`, `mypy`, and formatting checks on
every commit. You can also run all hooks manually:

```bash
pre-commit run --all-files
```

### 5. Verify the installation

```bash
multimind --version
pytest
```

If both commands succeed, your development environment is ready.

---

## Project Structure

```
multimind/
├── src/multimind/        # Source code
│   ├── core/             # Core domain logic (roles, topology, memory)
│   ├── adapters/         # Channel adapters (cli_reuse, free_api, ...)
│   ├── engine/           # Orchestration engine and group-chat runtime
│   ├── tui/              # Textual-based terminal user interface
│   └── cli/              # Command-line entry points
├── tests/                # Test suite (mirrors src/ layout)
├── docs/                 # Documentation
├── pyproject.toml        # Build, dependency, and tool configuration
└── ...
```

---

## Code Style

MultiMind enforces a consistent style across the codebase. All checks run in
pre-commit and in CI; a pull request cannot be merged until they pass.

### Ruff

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting. The
configuration lives in `pyproject.toml`.

```bash
ruff check .            # Lint
ruff format .           # Format
```

### Mypy

We use [Mypy](https://mypy-lang.org/) for static type checking. Type
annotations are **required** for all public functions and methods.

```bash
mypy src/multimind
```

### Type hints

- **All public functions and methods must have type hints** for parameters
  and return values.
- Prefer the standard library `typing` module and built-in generics
  (`list[str]` rather than `List[str]` on Python 3.10+).
- Use `from __future__ import annotations` at the top of modules where it
  improves forward-reference ergonomics.
- Avoid `Any` where a more specific type is available; document exceptions
  with a comment when `Any` is genuinely necessary.

### General conventions

- Maximum line length is **100 characters**.
- Use **4-space indentation** for Python; **2-space** for YAML/TOML (see
  `.editorconfig`).
- Write docstrings for public modules, classes, and functions (Google or
  reStructuredText style).
- Keep functions focused and small; extract reusable logic.

---

## Testing Requirements

A reliable test suite is essential for a project that orchestrates multiple
AI backends. We expect every contribution to maintain or improve test
coverage.

### Running tests

```bash
pytest                       # Run the full suite
pytest tests/unit            # Unit tests only
pytest -k memory             # Run tests matching a keyword
pytest --cov=multimind       # With coverage report
```

### Requirements

- **All existing tests must pass** before a pull request is merged.
- **Add tests for new features.** New code should ship with corresponding
  unit tests; integration tests may be required for end-to-end behaviour.
- **Add or update tests when fixing bugs** to prevent regressions. Ideally,
  the failing test is added first to demonstrate the bug, then the fix makes
  it pass.
- Aim to **maintain or increase overall coverage**. CI enforces a minimum
  coverage threshold; do not let it drop.
- Use deterministic, isolated tests. Mock external AI providers and network
  calls — do not make real API requests in the test suite.
- Follow the existing test layout under `tests/`, mirroring the `src/`
  structure.

---

## Pull Request Process

1. **Fork and branch.** Create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```
2. **Make your changes.** Keep commits focused — see
   [Commit Message Convention](#commit-message-convention).
3. **Run the checks locally** before pushing:
   ```bash
   pre-commit run --all-files
   pytest
   mypy src/multimind
   ```
4. **Update documentation** (`README.md`, docstrings, `CHANGELOG.md`) if your
   change affects user-facing behaviour.
5. **Open a pull request** against `main` using the provided template.
   - Link any related issues (`Closes #123`).
   - Describe what changed and why.
   - Note any breaking changes.
6. **Address review feedback.** Push additional commits rather than
   force-pushing during review; squash before merge if needed.
7. **Ensure CI is green.** All checks must pass for the PR to be merged.

A maintainer will review your PR. Reviews focus on correctness, test
coverage, API stability, and documentation. Once approved, a maintainer will
merge your contribution.

---

## Commit Message Convention

We follow the [Conventional Commits](https://www.conventionalcommits.org/)
specification. This enables automatic changelog generation and semantic
versioning.

### Format

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

### Types

| Type       | Purpose                                                        |
|------------|----------------------------------------------------------------|
| `feat`     | A new feature                                                  |
| `fix`      | A bug fix                                                      |
| `docs`     | Documentation-only changes                                     |
| `style`    | Code style changes (formatting, whitespace) — no logic change  |
| `refactor` | Code restructuring that neither fixes a bug nor adds a feature |
| `perf`     | Performance improvements                                       |
| `test`     | Adding or correcting tests                                     |
| `build`    | Changes to build system or dependencies                        |
| `ci`       | CI configuration changes                                       |
| `chore`    | Routine maintenance (tooling, configs)                         |
| `revert`   | Reverting a previous commit                                    |

### Examples

```
feat(memory): add semantic retrieval for long-term store

Implements vector-based retrieval over the long-term memory tier,
allowing roles to recall relevant context from prior sessions.

Closes #42
```

```
fix(adapters): handle expired tokens in browser_login channel

The browser_login adapter no longer crashes when a session token
expires; it now triggers a re-authentication flow.

Reported-by: Jane Doe
```

### Breaking changes

Indicate breaking changes with a `!` after the type/scope **or** with a
`BREAKING CHANGE:` footer:

```
feat(engine)!: switch default topology to parallel

BREAKING CHANGE: The default topology is now `parallel` instead of
`sequential`. Update configurations that rely on the old default.
```

---

## Releasing

Releases are managed by maintainers following Semantic Versioning. The
process is automated via CI:

1. The `main` branch is kept in a releasable state.
2. A maintainer tags a release (`v0.2.0`), which triggers the release
   pipeline.
3. The pipeline builds distributions, publishes to PyPI, and creates a
   GitHub Release with auto-generated notes.

Contributors do not need to manage versions directly — just follow the
commit conventions above.

---

## Questions?

- Open a [Discussion](https://github.com/multimind/multimind/discussions) for
  general questions.
- Open an [Issue](https://github.com/multimind/multimind/issues) for bugs
  and feature requests.
- Email **conduct@multimind.dev** for Code of Conduct matters.

Thank you for helping make MultiMind better!
