# Legacy Java TUI Development Guidelines

These guidelines are retained as historical guidance for Java/Lanterna terminal user interfaces.

The active Raven application is now a Spring Boot REST backend and no longer contains Java TUI code. Do not add new Lanterna screens or Java terminal windows to the Spring Boot application.

If Raven needs a textual interface, implement it as a separate Python client that consumes the REST API and OpenAPI contract exposed by:

```text
/v3/api-docs
/swagger-ui.html
```

Recommended stack for a future textual interface:

- Python Textual for the terminal UI;
- generated or typed Python API client from OpenAPI;
- HTTP calls to the Spring Boot REST backend.

The rest of this document applies only if a separate Java/Lanterna TUI project is intentionally created again.

## 1) Scope And Principles

- Treat the TUI as a real application surface, not as a debug console.
- Optimize for keyboard-first workflows, readable state, fast feedback, and predictable navigation.
- Keep terminal rendering separate from domain logic, graph orchestration, persistence, and external integrations.
- Prefer small, composable screens and panels over one large interactive class.
- Make all long-running work cancellable or clearly marked as running.
- Never display secrets, raw prompts, full document contents, credentials, or stack traces unless the user explicitly opens a diagnostic view designed for that purpose.

## 2) Project Structure

For standalone Java TUI projects, use a package layout aligned to application responsibilities:

```text
src/main/java/<base-package>/
  RavenApplication.java          # bootstrap only
  tui/                           # Lanterna screens, windows, panels, widgets
  tui/actions/                   # UI-triggered commands and command dispatch
  tui/state/                     # view state, selection state, filters
  services/                      # use-case orchestration
  graph/                         # LangGraph4j graph factories, nodes, state
  agents/                        # direct AI agent execution units
  repositories/                  # Neo4j and other persistence adapters
  model/                         # domain models and value objects
  config/                        # typed application configuration
  exceptions/                    # specific application exceptions
  utils/                         # stateless utilities only
```

For `raven`, the base package is `it.osint.raven`.

Spring-specific package rules from `BACKEND_JAVA_DEVELOPMENT_GUIDELINES.md` apply only when the project uses Spring. A standalone TUI must still preserve the same intent: clear ownership, thin entry points, domain-specific exceptions, low complexity, and safe logging.

## 3) Lanterna Screen Architecture

- Keep the application entry point limited to configuration, dependency wiring, and launching the first screen.
- Put Lanterna `Window`, `Panel`, layout, and widget construction under `tui`.
- Avoid mixing Neo4j queries, LLM calls, LangGraph4j graph execution, or file/network I/O directly inside widget callbacks.
- Widget callbacks should delegate to an action/service and update view state from the result.
- Use stable view models for screen state instead of reading mutable widget values across unrelated classes.
- Keep window close behavior explicit and always release terminal resources with try-with-resources or equivalent cleanup.
- Avoid global mutable UI state. If shared state is needed, pass a small application context object.

## 4) Keyboard And Navigation

- Every screen must be usable without a mouse.
- Provide deterministic focus order for forms, lists, tables, buttons, and dialogs.
- Reserve common keys consistently:
  - `Esc` closes dialogs or returns to the previous screen.
  - `Enter` activates the focused item or confirms a dialog.
  - Arrow keys move within lists, tables, menus, and tabs.
  - `/` opens search or filter where the screen has searchable content.
  - `?` opens contextual help when the screen has non-obvious commands.
- Do not overload the same key with different meanings in the same screen.
- Destructive actions require confirmation and must clearly identify the affected resource.

## 5) Layout And Terminal Compatibility

- Design for narrow terminals first; support at least `80x24`.
- Use responsive Lanterna layouts rather than fixed absolute coordinates.
- Keep important status, selection, and error information visible without horizontal scrolling.
- Truncate long identifiers safely with a middle ellipsis or a detail panel; never let UUIDs, paths, or URLs break the layout.
- Prefer tables/lists for scan-heavy data and dialogs for short focused tasks.
- Provide empty, loading, success, warning, and error states for every screen that depends on external data.
- Avoid color-only meaning; pair colors with labels, symbols, or status text.
- Keep color palettes readable on dark and light terminals.

## 6) Copy And Feedback

- Use short, action-oriented labels: `Open`, `Run`, `Cancel`, `Retry`, `Connect`.
- Avoid implementation wording in normal UI copy (`driver`, `stack trace`, `future`, `thread`) unless the screen is explicitly technical.
- Show immediate feedback when an action starts, succeeds, fails, or is cancelled.
- For recoverable failures, give the user a next action such as retry, edit configuration, or view diagnostics.
- Keep diagnostic detail behind a deliberate action so normal workflows remain calm and readable.

## 7) Long-Running Work

- Run Neo4j queries, LLM calls, LangGraph4j graph execution, and network/file operations off the UI event path.
- Show progress where available; otherwise show a running state with elapsed time.
- Provide cancellation for operations that may exceed a few seconds.
- Prevent duplicate submissions while an operation is running unless repeated execution is intentionally supported.
- Marshal state changes back through a controlled UI update path; do not update Lanterna widgets concurrently from arbitrary worker threads.
- Persist or checkpoint graph work only through service/graph layers, not from screen classes.

## 8) Neo4j Integration

- Isolate Neo4j access under `repositories` or a persistence adapter package.
- Use parameterized Cypher queries; never concatenate user input into query strings.
- Keep sessions, transactions, cursors, and drivers resource-safe.
- Centralize connection configuration and validate it before first use.
- Return domain models or view models from repositories; do not leak driver records into TUI classes.
- For large result sets, page or stream intentionally and cap default limits.

## 9) LangChain4j And LangGraph4j Integration

- Direct LLM agent classes live under `agents`; graph factories, nodes, and graph state live under `graph`.
- Keep prompts, model configuration, tool wiring, and graph execution out of TUI widgets.
- Do not log or display raw prompts, document contents, generated sensitive content, tokens, or credentials.
- Use specific graph/agent exception types with safe messages for the TUI.
- Track graph stage, current node, and correlation id where useful for diagnostics.
- Store large graph state by reference when persistence or resume is required; avoid keeping large payloads in terminal view state.
- Prefer deterministic graph tests with mocked model responses before wiring live LLM providers.

## 10) Configuration And Secrets

- Load configuration through a typed configuration object.
- Support environment variables for secrets and connection details.
- Never commit credentials, tokens, private keys, database passwords, or model provider keys.
- Mask secrets in diagnostics and connection summaries.
- Validate required configuration at startup and show a clear terminal-safe message when invalid.

## 11) Logging And Diagnostics

- Use SLF4J with parameterized logs.
- Log operation names, correlation ids, graph stages, resource ids, and durations when available.
- Do not use `System.out`, `System.err`, or `printStackTrace()` for application diagnostics.
- Keep user-facing errors safe and concise; keep detailed diagnostics in logs or a dedicated diagnostic view.
- Avoid logging full user-entered queries when they may contain sensitive OSINT targets, prompts, credentials, or document text.

## 12) Exceptions

- Do not throw generic `RuntimeException` directly from application code.
- Define specific exceptions for configuration, persistence, graph execution, agent execution, user input validation, and unsupported actions.
- Catch exceptions at screen/action boundaries only to convert them into safe user feedback.
- Preserve causes when wrapping lower-level failures.
- Always release terminal, Neo4j, file, network, and graph resources on failure.

## 13) Testing And Quality Gates

- Add unit tests for services, repositories, graph nodes, input validation, and formatting helpers.
- Add focused TUI tests for screen construction, action dispatch, view-state transitions, and key bindings where practical.
- Use mocked Neo4j, LangChain4j, and LangGraph4j dependencies for deterministic tests.
- Verify packaging with `mvn -q -DskipTests package` at minimum.
- For behavior-bearing code, run the relevant test suite before closing the task.
- Manually smoke-test the packaged jar in a terminal when changing bootstrap, navigation, terminal lifecycle, or key bindings.

## 14) Accessibility And Operability

- Keep keyboard shortcuts discoverable through contextual help.
- Maintain sufficient contrast and avoid relying only on color.
- Make errors readable in plain text.
- Do not animate or continuously repaint unless the screen truly needs live updates.
- Provide a clean shutdown path from every top-level screen.
- Keep terminal state sane after crashes or interrupts; restore the screen whenever possible.

## 15) Definition Of Done For TUI Changes

- `dev-guides/TUI_DEVELOPMENT_GUIDELINES.md` has been reviewed before implementation.
- TUI classes stay under `tui`; domain logic stays outside widget callbacks.
- Long-running work is asynchronous, cancellable where practical, and protected against duplicate submission.
- Neo4j, LangChain4j, and LangGraph4j integrations are isolated behind services/adapters.
- Secrets and sensitive content are not displayed or logged.
- Layout works in an `80x24` terminal and handles empty/loading/error states.
- Keyboard navigation and close behavior are deterministic.
- Specific exceptions and safe user-facing messages are used.
- Relevant tests or smoke checks have been run and documented.
