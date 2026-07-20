# Changelog

All notable changes to the **MultiMind** project will be documented in this
file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Placeholder for upcoming changes. Move items here before a release.

### Changed

- _Nothing yet._

### Deprecated

- _Nothing yet._

### Removed

- _Nothing yet._

### Fixed

- _Nothing yet._

### Security

- _Nothing yet._

---

## [0.1.0] - 2026-07-20

The initial public release of MultiMind — a multi-AI collaboration CLI
agent that orchestrates several AI roles through a configurable topology
of channel adapters.

### Added

- **Five channel types** for flexible AI backend connectivity:
  - `cli_reuse` — wrap an existing local CLI application as an AI channel.
  - `free_api` — connect to free-tier or open AI APIs.
  - `browser_login` — drive browser-based AI services via authenticated
    sessions.
  - `public_endpoint` — consume publicly exposed AI inference endpoints.
  - `local_fallback` — an offline rule-based / echo fallback used when all
    other channels are unavailable.
- **Group chat orchestration** between multiple AI roles:
  - `Leader` — high-level planning, goal decomposition, and final answers.
  - `Dispatcher` — routes sub-tasks to the appropriate Executor(s).
  - `Executor` — carries out concrete sub-tasks and returns results.
- **Dynamic topology switching** — switch between `sequential`,
  `parallel`, `pipeline`, and `star` topologies at runtime based on task
  complexity and available channels.
- **Three-tier memory system**:
  - _Short-term_ — per-session working memory for the active conversation.
  - _Mid-term_ — cross-session task memory and intermediate results.
  - _Long-term_ — persisted, summarised knowledge store with semantic
    retrieval.
- **Automatic Git commits** — MultiMind can snapshot memory and
  conversation state to a Git repository for auditability and rollback.
- **Textual-based TUI** — an interactive terminal user interface for
  multi-role chat, channel status, and memory inspection.
- **CLI entry point** — `multimind chat` launches the TUI; additional
  subcommands cover configuration, memory, and diagnostics.
- **Configuration system** — YAML/TOML configuration with environment
  variable overrides and a layered discovery mechanism.
- **Project scaffolding** — `pyproject.toml`, `LICENSE` (Apache-2.0),
  `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, and
  `.editorconfig` for a production-ready open-source foundation.
- **Test suite** — initial unit and integration tests with `pytest`.

### Security

- Sensitive files (`.env`, `.multimind/`) are git-ignored by default.
- Channel credentials are read from environment variables and are never
  written to logs.

---

## Versioning Summary

- **MAJOR** — incompatible API changes.
- **MINOR** — backwards-compatible feature additions.
- **PATCH** — backwards-compatible bug fixes.

Pre-release versions (`0.x.y`) indicate that the public API is not yet
considered stable and may change between minor releases.

---

[Unreleased]: https://github.com/multimind/multimind/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/multimind/multimind/releases/tag/v0.1.0
