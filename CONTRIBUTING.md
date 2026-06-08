# Contributing to DepthSight

First off, thank you for considering contributing to DepthSight! It's people like you that make DepthSight a great tool for the trading community.

As a high-performance, multi-tenant algorithmic trading platform, we have a few guidelines to keep the codebase maintainable and secure.

## Code of Conduct

By participating in this project, you agree to abide by the terms of our Code of Conduct (be kind, be professional, and focus on technical excellence).

## How Can I Contribute?

### Reporting Bugs
* Check the existing Issues to see if the bug has already been reported.
* If not, open a new Issue. Include steps to reproduce, expected behavior, and your environment details (OS, Python version, Docker version).

### Suggesting Enhancements
* Open an Issue with the tag `enhancement`.
* Describe the use case and how it benefits the wider trading community.

### Pull Requests
1. Fork the repo and create your branch from `main`.
2. If you've added code that should be tested, add tests.
3. If you've changed APIs, update the documentation.
4. Ensure the test suite passes.
5. Make sure your code lints and follows the project's style.

## Development Setup

### Backend (Python)
We use **Ruff** for linting and formatting. Please run it before committing:

```bash
ruff check . --fix
ruff format .
```

### Frontend (React/Vite)
We use **ESLint** and **Prettier**. Ensure your editor is configured to use them or run:

```bash
cd frontend
npm run lint
```

## Navigating the Monoliths

DepthSight contains several core modules that are intentionally monolithic for performance and architectural reasons:
* `bot_module/controller.py`: The heart of the trading engine.
* `bot_module/strategy.py`: Contains the logic for all strategy types and the Visual Builder interpreter.
* `api/depthsight_api.py`: The main REST entry point.

**Tip:** When working in these files, use a modern IDE with a good "Symbol Search" or "Outline" view to jump between methods.

## Testing Standards

We use `pytest` for all backend testing. 

```bash
pytest
```

**End-to-End (E2E) Tests:**
Many tests in `tests/` interact with exchange testnets. If you don't provide your own `TESTNET_*` keys in `.env`, these tests will skip automatically. This is expected. If you are working on a specific exchange integration, please add your keys to verify your changes.

## Security First

* **NEVER** commit real API keys, secrets, or personal data.
* We use Fernet encryption for API keys in the database. If you touch the encryption logic, ensure you maintain backward compatibility.
* All user data must be isolated by `user_id`. Always verify that your queries/filters include a user context.

## Commercial Use & Licensing

DepthSight is licensed under the **GNU AGPLv3**. While contributions are welcome from everyone, please remember that commercial SaaS usage of this codebase without open-sourcing modifications requires a separate commercial license.

To accept your contributions, we may require you to sign a Contributor License Agreement (CLA). This ensures we have the necessary rights to dual-license the project to enterprise users, which helps fund the open-source development.

*Thank you for being part of the DepthSight ecosystem!*
