# Python TUI Development Guidelines

These guidelines define the active development standard for the Raven Python/Textual
application.

## 1. Scope and principles

- Treat the TUI as a product surface, not as a debug console.
- Optimize for keyboard-first workflows, readable state, fast feedback, and predictable
  navigation.
- Keep rendering separate from domain logic, graph orchestration, persistence, and external
  integrations.
- Make long-running work cancellable or clearly marked as running.
- Never display secrets, raw prompts, credentials, full source documents, or stack traces in
  normal application views.

## 2. Project structure

Use a `src` layout with the following ownership boundaries:

```text
src/raven/
  app.py                 # bootstrap and dependency wiring only
  tui/
    screens/             # navigable screens and modal screens
    widgets/             # reusable presentation components
    state/               # stable view state
    actions/             # UI commands and dispatch
  services/              # use-case orchestration
  graph/                 # graph factories, nodes, and graph state
  agents/                # direct LLM execution units
  repositories/          # persistence adapters
  models/                # domain models and value objects
  config/                # typed application configuration
  exceptions/            # specific application exceptions
```

Do not put network calls, database queries, graph execution, or model calls in widget event
handlers. Handlers delegate to actions or services and only translate results into view state.

## 3. Screens and widgets

- Keep screens focused on one user workflow.
- Extract reusable presentation into `tui/widgets`.
- Keep TCSS in dedicated files; avoid large inline style blocks.
- Prefer explicit screen state over reading unrelated mutable widget values.
- Avoid global mutable UI state; pass a small typed application context when shared state is
  required.

## 4. Keyboard and navigation

- Every screen must work without a mouse.
- Use a deterministic focus order.
- `Esc` closes dialogs or returns to the previous screen.
- `Enter` activates the focused item or confirms a dialog.
- Arrow keys navigate lists, tables, menus, and tabs.
- `/` opens search where searchable content exists.
- `?` opens contextual help for non-obvious commands.
- `q` cleanly exits from a top-level screen.
- Destructive actions require confirmation and must name the affected resource.

## 5. Layout and terminal compatibility

- Support at least an 80×24 terminal.
- Provide a compact fallback for artwork or content that exceeds narrow terminals.
- Keep status and error information visible without horizontal scrolling.
- Represent empty, loading, running, success, warning, cancelled, and error states when a view
  depends on external work.
- Never rely on color alone; pair it with text or a symbol.
- Keep the palette readable on dark and light terminal themes.

## 6. Long-running work

- Run LLM calls, graph execution, database work, and network/file operations in Textual workers,
  not on the message-processing path.
- Show progress when available and elapsed/running state otherwise.
- Provide cancellation for work that may exceed a few seconds.
- Prevent accidental duplicate submissions.
- Update widgets through controlled UI messages or reactive state.

## 7. Graph, LLM, and persistence boundaries

- Put direct model agents under `agents` and graph state/nodes under `graph`.
- Isolate Neo4j or other persistence access under `repositories`.
- Use parameterized queries and resource-safe sessions/transactions.
- Keep prompts, provider configuration, and tool wiring out of widgets.
- Prefer deterministic graph tests with mocked model responses before enabling live providers.
- Track a safe correlation ID and graph stage for diagnostics; do not log sensitive payloads.

## 8. Configuration, logging, and errors

- Load settings through typed configuration objects and environment variables.
- Never commit credentials, tokens, private keys, or database passwords.
- Use Python `logging`; do not use `print` for diagnostics.
- Log operation names, correlation IDs, safe resource IDs, stages, and durations.
- Define specific exceptions for configuration, persistence, graph execution, agent execution,
  validation, and unsupported actions.
- Convert exceptions to concise user feedback only at action/screen boundaries.

## 9. Tests and quality gates

- Add unit tests for services, repositories, graph nodes, validation, and formatting helpers.
- Add Textual pilot tests for screen construction, navigation, view-state transitions, actions,
  responsive behavior, and key bindings.
- Mock LLM, database, and network dependencies for deterministic tests.
- Before completing behavior-bearing work, run:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

- Smoke-test the installed `raven` entry point when changing bootstrap, navigation, terminal
  lifecycle, or packaging.

## 10. Definition of done

- This guide was reviewed before implementation.
- TUI presentation remains under `tui`; business logic remains outside widget callbacks.
- Terminal layout works at 80×24 and has appropriate compact behavior.
- Keyboard navigation, help, and shutdown are deterministic.
- Sensitive content is neither displayed nor logged.
- Relevant tests, lint, formatting, and an entry-point smoke test pass.
