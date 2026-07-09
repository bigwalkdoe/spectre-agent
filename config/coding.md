# Coding Standards

## General

- Follow existing code patterns in the project.
- Use descriptive, intention-revealing names.
- Keep functions small and focused — one responsibility per function.
- Favor composition over inheritance.
- No commented-out code — delete it.
- No print/console.log statements in production code.

## Python

- Format with `ruff format`.
- Lint with `ruff check`.
- Type-check with `mypy --strict`.
- Use FastAPI dependency injection for shared logic.
- SQLAlchemy async sessions for database operations.
- Pydantic models for request/response validation.

## TypeScript / React

- Format with `prettier`.
- Lint with `eslint`.
- Use functional components with hooks.
- Type props explicitly with TypeScript interfaces.
- Tailwind CSS for styling — no CSS modules or styled-components.

## Git

- Write conventional commits: `type(scope): description`
- Types: `feat`, `fix`, `chore`, `refactor`, `docs`, `test`, `ci`, `perf`
- Keep commits atomic — one logical change per commit.
