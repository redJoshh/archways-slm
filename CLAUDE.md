# archways-assistant
Local small-language-model assistant for UST Archways. The Java/Spring app lives in a separate repo.
The model runs via Ollama and emits a `search_announcements` tool call; the Spring app executes it against Postgres.

## Commands
- Setup: `uv sync`
- Lint / format: `uv run ruff check .` / `uv run ruff format .`
- Test: `uv run pytest`

## Rules
- Python 3.12, managed by uv. Commit `uv.lock`, never `.venv`.
- Never commit secrets, `.env`, model weights, or real user data.
- Never connect to the team's database. Use seed data in `data/seed/`.
- Announcements are fetched at query time via the tool. Never train on them as facts.
- Small commits, Conventional Commits (`feat:`, `fix:`, `docs:`).