# AGENTS.md

## Mission and priorities
- Treat the contest specification, evaluation criteria, and documented contracts as authoritative.
- Prioritize correct, demonstrable, end-to-end behavior over feature count or architectural elegance.
- Follow XP: simplicity, feedback, communication, courage, and respect.
- Apply Clean Code, KISS, DRY, YAGNI, and SOLID pragmatically; do not create speculative abstractions.
- Leave touched code cleaner than you found it without expanding scope.

## Clean Python
- Use descriptive names, small cohesive functions, guard clauses, and explicit dependencies.
- Separate domain logic from I/O, frameworks, and infrastructure.
- Minimize side effects, shared mutable state, nesting, and coupling; prefer composition.
- Use modern Python and type annotations on all function signatures; avoid unnecessary classes.
- Prefer the standard library when it is sufficient; never use mutable default arguments.
- Explain *why* in comments; delete dead code and stale comments.
- Catch specific exceptions at appropriate boundaries; never silently swallow errors.

## Workflow: BDD + TDD
- Start with a testable acceptance criterion, expressed as Given / When / Then when appropriate.
- Use `pytest-bdd` for business-facing acceptance scenarios and `pytest` for unit/integration tests.
- Work outside-in: write a failing acceptance scenario, then use Red -> Green -> Refactor on the smallest unit.
- Implement only enough behavior to pass; refactor with all tests green.
- Test observable behavior, boundaries, missing/invalid data, and failure paths, not implementation details.
- Keep tests fast, deterministic, isolated, and readable; use Arrange / Act / Assert.
- Use realistic fixtures; avoid excessive mocking. Add regression tests for bug fixes.
- Do not weaken or delete tests to make a change pass; avoid duplicating every unit test in Gherkin.

## Missing data and unknown requirements
- Never invent data, results, APIs, files, credentials, or completed functionality.
- Distinguish missing, null, empty, invalid, synthetic, and derived values; preserve provenance.
- Validate data contracts at boundaries and fail clearly for absent required fields.
- Represent optional missing values explicitly; do not silently substitute business-altering defaults.
- First inspect available evidence and contracts. Ask when ambiguity materially affects correctness.
- If clarification is unavailable, use the smallest reversible assumption, document it, and test it.
- Prefer a complete vertical slice over placeholders or hardcoded outputs; make unsupported operations explicit.

## Reliability, security, and performance
- Fail fast on invalid invariants; degrade gracefully only for recoverable failures.
- Use explicit timeouts and bounded retries with backoff for transient external failures.
- Make relevant operations idempotent and failure states observable.
- Never expose secrets in source, logs, or version control; validate untrusted input.
- Choose appropriate algorithms; measure bottlenecks before optimizing.
- Ensure deterministic tests and reproducible environments; commit `uv.lock` when generated.

## Tools and verification
- Use `uv` for Python environment, dependencies, and execution; never use `pip`.
- Use `make` targets for routine workflows.
- Use Ruff for linting/formatting, strict mypy for types, pytest and pytest-bdd for tests.
- Avoid `Any`, `type: ignore`, and lint suppressions without a documented reason.
- Run `make check` before completion; verify the documented execution entry point.
- Report exactly what passed, what remains unverified, and any known limitations.
- Never claim a feature, performance result, or test passed without evidence.


## Specifics
- Never change the code without a documented reason.
- Keep the code base as small as possible but correct: Claude via the Anthropic SDK, plain tool calls, DuckDB and
  Chainlit. Do not add agent frameworks (LangChain, LangGraph, ...) without a documented need the plain loop cannot meet.
- The model never reads the data directly: it sees metadata only and generates SQL, which is checked and run by
  `database.py`. Keep tools small and single-purpose.
- Safety is deterministic: the SQL allowlist, the read-only sandboxed connection, timeouts, row caps, round limits
  and cost budgets are the boundary. The reviewer agent is an extra check, never the only one.
- The seed data is synthetic. Never copy real people, runs or other real data into it.
