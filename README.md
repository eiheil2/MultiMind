# MultiMind

> A multi-AI collaboration CLI agent that orchestrates several AI roles through a configurable topology of channel adapters.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Tests](https://github.com/multimind/multimind/actions/workflows/tests.yml/badge.svg)](https://github.com/multimind/multimind/actions/workflows/tests.yml)
[![Code style: Ruff](https://img.shields.io/badge/code%20style-ruff-261230.svg)](https://docs.astral.sh/ruff/)
[![Checked with mypy](https://img.shields.io/badge/mypy-checked-blue.svg)](http://mypy-lang.org/)
[![PyPI version](https://img.shields.io/pypi/v/multimind.svg)](https://pypi.org/project/multimind/)

MultiMind turns several AI backends into a single, coordinated team. Instead of
chatting with one model, you orchestrate a **Leader**, a **Dispatcher**, and one
or more **Executors** that collaborate to solve complex tasks. Roles can be
served by any of five channel types — from a free API to a local CLI tool — and
the topology that wires them together can be switched at runtime.

---

## Table of Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Development Setup](#development-setup)
- [Contributing](#contributing)
- [License](#license)

---

## Features

### Five Channel Types

MultiMind connects to AI backends through pluggable channel adapters. Mix and
match them per role:

| Channel            | Description                                                        |
|--------------------|--------------------------------------------------------------------|
| **CLI reuse**      | Wrap an existing local CLI application as an AI channel.           |
| **Free API**       | Connect to free-tier or open AI APIs.                              |
| **Browser login**  | Drive browser-based AI services via authenticated sessions.        |
| **Public endpoint**| Consume publicly exposed AI inference endpoints.                   |
| **Local fallback** | An offline, rule-based / echo fallback when all else is unavailable.|

### Group Chat Between AI Roles

Multiple AI roles collaborate in a structured group chat:

- **Leader** — decomposes high-level goals, plans the workflow, and
  synthesises the final answer.
- **Dispatcher** — routes sub-tasks to the most suitable Executor(s) based on
  capabilities and channel availability.
- **Executor** — carries out concrete sub-tasks (code, analysis, search) and
  returns structured results.

### Dynamic Topology Switching

Switch how roles are wired together at runtime based on task complexity and
available channels:

- `sequential` — roles run one after another.
- `parallel` — multiple Executors run concurrently.
- `pipeline` — output of one role feeds the next in a chain.
- `star` — the Dispatcher broadcasts to all Executors and aggregates results.

### Three-Tier Memory System

- **Short-term** — per-session working memory for the active conversation.
- **Mid-term** — cross-session task memory and intermediate results.
- **Long-term** — persisted, summarised knowledge store with semantic
  retrieval.

### Layered Context Assembly

All context injected into a prompt is built by a single
`ContextBuilder` (`engine/context.py`) — no more ad-hoc `context[-N:]`
slicing scattered across the codebase:

- **L0 active window** — the most recent turns, kept verbatim and
  filled newest-first within the token budget.
- **L1 keyframes + facts** — task-intent keyframes and `A→B` relation
  facts distilled from older history.
- **L2 relevance retrieval** — character-bigram relevance ranking
  against the current task, with zero external dependencies.
- **CJK-aware token budgets** — Chinese text is estimated per
  character (ASCII per 4), trimmed strictly against each provider's
  `max_tokens` window.

### Automatic Git Commits

MultiMind can snapshot memory and conversation state to a Git repository,
giving you full auditability and the ability to roll back to any prior state.

### Textual-Based TUI

An interactive terminal user interface (powered by
[Textual](https://textual.textualize.io/)) lets you watch the multi-role
conversation unfold, inspect channel status, and browse memory — all from the
comfort of your terminal.

---

## Quick Start

Install MultiMind from PyPI:

```bash
pip install multimind
```

Launch the TUI and start a multi-AI chat session:

```bash
multimind chat
```

You can also run a one-off prompt directly from the command line:

```bash
multimind run "Summarise the latest changes in this repository and draft a release note."
```

That's it. On first run, MultiMind will guide you through configuring at least
one channel.

---

## Architecture

MultiMind is organised in three layers: **adapters** (how we talk to AI
backends), **engine** (how roles collaborate), and **core** (shared domain
logic and memory).

```
                         ┌─────────────────────────────────────┐
                         │              TUI / CLI              │
                         │         (Textual interface)         │
                         └─────────────────┬───────────────────┘
                                           │
                ┌──────────────────────────▼───────────────────────────┐
                │                      ENGINE LAYER                    │
                │   (Orchestration: group chat, topology, scheduling)  │
                │                                                      │
                │   ┌───────────┐  ┌────────────┐  ┌──────────────┐   │
                │   │  Leader   │──│ Dispatcher │──│  Executors   │   │
                │   └───────────┘  └────────────┘  └──────────────┘   │
                │                                                      │
                │   Topologies: sequential | parallel | pipeline | star│
                └──────────┬───────────────────────────┬───────────────┘
                           │                           │
        ┌──────────────────▼──────────┐  ┌─────────────▼──────────────┐
        │        CORE LAYER           │  │       ADAPTER LAYER        │
        │  (Domain logic & memory)    │  │  (AI backend channels)     │
        │                             │  │                            │
        │  ┌───────────────────────┐  │  │  ┌────────────────────┐    │
        │  │   3-Tier Memory       │  │  │  │  CLI Reuse         │    │
        │  │  ┌─────────────────┐  │  │  │  ├────────────────────┤    │
        │  │  │ Short-term      │  │  │  │  │  Free API          │    │
        │  │  ├─────────────────┤  │  │  │  ├────────────────────┤    │
        │  │  │ Mid-term        │  │  │  │  │  Browser Login     │    │
        │  │  ├─────────────────┤  │  │  │  ├────────────────────┤    │
        │  │  │ Long-term       │  │  │  │  │  Public Endpoint   │    │
        │  │  └─────────────────┘  │  │  │  ├────────────────────┤    │
        │  └───────────────────────┘  │  │  │  Local Fallback    │    │
        │                             │  │  └────────────────────┘    │
        │  ┌───────────────────────┐  │  └─────────────┬──────────────┘
        │  │   Auto Git Commits    │◄─┼────────────────┘
        │  └───────────────────────┘  │
        └─────────────────────────────┘
```

- The **Adapter Layer** normalises five heterogeneous AI backends behind a
  common `Channel` interface.
- The **Engine Layer** orchestrates role collaboration and applies the chosen
  topology, routing messages between Leader, Dispatcher, and Executors.
- The **Core Layer** holds the domain model, the three-tier memory system, and
  the automatic Git commit subsystem that persists state.

---

## Configuration

MultiMind is configured through a `multimind.toml` (or `multimind.yaml`) file
discovered from the current directory, the user config directory, or an
explicit `--config` flag. Environment variables override file values.

```toml
# multimind.toml — example configuration

[topology]
default = "parallel"          # sequential | parallel | pipeline | star
switch_on_failure = true      # fall back to a simpler topology if a role fails

[roles.leader]
channel = "free_api"
model = "gpt-oss:20b"

[roles.dispatcher]
channel = "free_api"
model = "gpt-oss:20b"

[[roles.executors]]
name = "coder"
channel = "cli_reuse"
command = ["my-local-llm", "--chat"]

[[roles.executors]]
name = "researcher"
channel = "browser_login"
service = "chatgpt"

[memory]
short_term_limit = 50          # max messages kept in working memory
mid_term_ttl_hours = 168       # one week
long_term_store = "~/.multimind/memory"

[git]
enabled = true
repo = "~/.multimind/state.git"
auto_commit = true
commit_interval_messages = 20  # commit after every 20 messages
```

Environment variables follow the pattern `MULTIMIND_<SECTION>_<KEY>`:

```bash
export MULTIMIND_TOPOLOGY_DEFAULT=star
export MULTIMIND_ROLES_LEADER_CHANNEL=free_api
```

A complete annotated example ships in `examples/multimind.example.toml`.

---

## Development Setup

MultiMind targets **Python 3.10+**. To set up a local development
environment:

```bash
# 1. Clone the repository
git clone https://github.com/multimind/multimind.git
cd multimind

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # On Windows: .venv\Scripts\activate

# 3. Install in editable mode with development dependencies
pip install --upgrade pip
pip install -e ".[dev]"

# 4. Install pre-commit hooks
pre-commit install

# 5. Run the test suite
pytest
```

The development extras (`[dev]`) include `ruff`, `mypy`, `pytest`,
`pytest-cov`, and `pre-commit`. Pre-commit will automatically lint, type-check,
and format your code on every commit.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contribution workflow,
coding standards, and commit message conventions.

---

## Contributing

Contributions of all kinds are welcome — bug reports, feature ideas,
documentation, and pull requests.

Please read our [Contributing Guide](CONTRIBUTING.md) to get started, and note
that all interactions are governed by the
[Code of Conduct](CODE_OF_CONDUCT.md).

---

## License

MultiMind is licensed under the **Apache License, Version 2.0**. See
[LICENSE](LICENSE) for the full text.

```
Copyright 2024 MultiMind Contributors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```
