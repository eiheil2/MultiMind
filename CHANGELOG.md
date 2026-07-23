# Changelog

All notable changes to the **MultiMind** project will be documented in this
file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Layered context assembly (`engine/context.py`)** — a new
  `ContextBuilder` module that replaces the scattered hard-coded
  `context[-N:]` / `content[:N]` truncations with a single, unified
  three-layer design:
  - **L0 active window** — recent turns kept verbatim, newest-first
    budget filling.
  - **L1 keyframes + fact extraction** — task-intent keyframes
    (e.g. "请实现登录功能") and relation facts ("系统→JWT认证") distilled
    from older history.
  - **L2 relevance retrieval** — character-bigram relevance ranking
    against the current task, zero external dependencies.
- **CJK-aware token estimation** — `estimate_tokens()` /
  `count_char_classes()` count CJK per character and ASCII per 4
  characters; every emitted `Message` is annotated with `layer` and
  `tokens` metadata, and strict budget trimming has no hidden "safety
  floor".
- **`ContextStats` diagnostics** — `ContextBuilder.last_stats` reports
  turns, per-layer counts and token usage for every build.
- **Real channel adapters** — the five adapters now perform real I/O
  instead of returning fixed mock strings:
  - `APIClientAdapter` / `PublicEndpointAdapter` — OpenAI-compatible
    SSE streaming over `httpx` (injectable transport for tests).
  - `LocalAdapter` — Ollama NDJSON streaming.
  - `CLIReuseAdapter` — real subprocess invocation with `{prompt}`
    argv templating or stdin piping, streaming stdout reads and
    per-read timeouts.
- **`adapters/streaming.py`** — shared SSE/NDJSON parsing and
  OpenAI `messages` conversion helpers.
- **New test suites** — `tests/unit/test_context.py` (36 tests for the
  layered builder) plus real-behaviour adapter tests driven by
  `httpx.MockTransport` and real subprocesses.

### Changed

- **`Orchestrator` delegates context assembly** — `_build_prompt` now
  renders an already-built context; the new `_provider_max_tokens`
  helper derives the per-role budget from `ProviderConfig.max_tokens`
  (reserving output space). `Orchestrator.run` also honours
  `max_rounds` instead of the previous hard-coded two-round break.
- **`MemoryManager.assemble_context` delegates to `ContextBuilder`**
  and then appends its tier-specific mid/long-term memories
  (`[记忆·mid]` / `[档案·long]` roles), keeping the builder generic.
- **`CLIReuseAdapter` no longer re-splices context** — context is
  assembled once upstream; the adapter only forwards the prompt.
- **Cyber-styled UI refresh** — the Textual TUI gains a neon-on-dark
  theme, ASCII banner, role-icon bubbles with coloured borders, a
  dashboard-style status panel, and structured event rendering; the
  CLI chat header now shows the ASCII banner with version info.
- **Test contracts updated for the new context behaviour** — the
  strict-budget contract replaces the old five-message safety floor,
  `default_roles` assertions check structure instead of a hard-coded
  headcount, usage-recording is parametrized across all five adapters,
  and Orchestrator tests now verify the `ContextBuilder` integration
  through a real subprocess-backed provider.

### Fixed

- **`BrowserAdapter` degradation bug** — Playwright launch failures
  (e.g. `TargetClosedError` on headless servers without an X server)
  were not `AdapterError` and slipped past the `except AdapterError`
  fallback; all launch errors are now wrapped so stub-mode degradation
  works, and partially-initialised resources are cleaned up.
- **TUI rendered raw event objects** — orchestrator events were
  written directly to the chat log (showing `repr`s); events are now
  aggregated into proper role bubbles.
- **Python 3.10 compatibility** — subprocess timeout handling no
  longer relies on the 3.11-only `asyncio.timeout()`.
- **Async-iterator abstract signatures** — `AIAdapter.ask` and
  `SiteAdapter.extract_stream` are declared as plain `def` returning
  `AsyncIterator`, matching their async-generator implementations.

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
