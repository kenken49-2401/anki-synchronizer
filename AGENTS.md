# Repository Guidelines

## Project Structure & Module Organization

- `web/` contains the GitHub Pages interfaces: `study-atlas.html` and `study-cloud-ui.mjs` implement Study Atlas; `app.js` and `vault.mjs` support Anki Atlas.
- Root-level Python modules implement Anki integration, encryption, site generation, and the earlier MCP prototype. Project dependencies and Python settings live in `pyproject.toml`.
- `tests/` contains Python and Node.js tests. Deployment and synchronization automation live in `.github/workflows/`.
- Consult `README.md`, `DASHBOARD.md`, and `ACTIONS_SETUP.md` for setup and deployment details.

## Build, Test, and Development Commands

- `python -m pip install -e '.[dev]'`: install the project and test dependencies with Python 3.12.
- `python -m pytest`: run the Python test suite.
- `node --test tests/study-quantity.test.mjs`: test daily and total task allocation.
- `python -m http.server 8000 --directory web`: serve the static UI locally; browser crypto or GitHub integration may require a secure context and configured credentials.

## Coding Style & Naming Conventions

Follow the surrounding module's style; keep changes focused. Use four-space indentation and snake_case for Python, and existing JavaScript conventions for browser code. Name Python tests `test_*.py` and Node tests `*.test.mjs`. Preserve existing Japanese UI labels and ensure layouts work on mobile screens.

## Testing Guidelines

Add focused tests for changed behavior, especially synchronization, encryption, and data migration. Run relevant Node or Python tests and exercise affected UI flows. Do not use real user data or secrets in fixtures. Test missing, conflicting, and older records when changing storage formats.

## Commits & Pull Requests

Recent commits use short, descriptive English or Japanese subjects, often phrased as actions. Pull requests should explain the user-visible change and verification; link relevant issues and include screenshots for visual changes. Keep Study Atlas UI publication separate from Anki synchronization where possible.

## Security & Configuration

Never commit tokens, passwords, plaintext Anki collections, or private study records to this public repository. Treat encrypted study data and private ChatGPT snapshots as separate stores; preserve conflict handling and obtain explicit authorization before changing what private data is shared.
