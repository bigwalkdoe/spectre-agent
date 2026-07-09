# Testing Standards

## Python

- **Framework**: pytest
- **Coverage target**: 80%+ for new code
- **Async tests**: pytest-asyncio
- **HTTP tests**: httpx (TestClient for FastAPI)
- **Database tests**: Testcontainers or SQLite in-memory for unit tests; dedicated test DB for integration
- **Fixtures**: shared fixtures in `conftest.py`
- **Mocking**: pytest-mock (unittest.mock wrapper)

## TypeScript

- **Framework**: vitest or jest
- **Coverage target**: 80%+
- **React testing**: @testing-library/react
- **Mocking**: vi (vitest) or jest.mock

## General

- Write tests before or alongside implementation.
- Test behavior, not implementation details.
- Use descriptive test names that read like sentences.
- One assertion concept per test.
