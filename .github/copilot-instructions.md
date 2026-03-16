# Copilot Instructions

## Project

- **Name**: ESG GroupChat PoC
- **Framework**: Microsoft Agent Framework RC (Python)
- **Python**: >= 3.11

## Specifications

- Always refer to the Markdown files under `specs/` for design and behavior specifications.

## Coding Conventions

- Type hints are **required** for all function signatures and variables where types are not obvious.
- Use `async` / `await` consistently — do not mix synchronous and asynchronous patterns.
- Define data models with **Pydantic** (`BaseModel` / `Field`).

## Testing

- Use **pytest** with **pytest-asyncio** for async test functions.
- Use `unittest.mock.MagicMock` and `unittest.mock.AsyncMock` for mocking.

## Language

- Code comments and variable/function names must be in **English**.
- User-facing messages (prompts, UI text) may be in **Japanese**.
