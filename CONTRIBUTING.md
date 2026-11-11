# Contributing to IDEN

The full guide is in the documentation, under [Contributing](doc/contributing/index.md):
setting up, the conventions, migrations and testing. The short version:

1. Branch from `dev`; one logical change per commit.
2. From `provider/` (and the same in `engine/` and `kiosk/server/`), all four must be clean:

   ```bash
   uv run ruff format .
   uv run ruff check .
   uv run pyright
   uv run pytest
   ```

   From `web/`: `pnpm lint`, `pnpm typecheck`, `pnpm build`.

3. A change to a model needs a migration (`uv run alembic revision --autogenerate`, then read it).
4. A new endpoint documents itself in `/docs`, and a fixed bug gets a test that failed before it.
5. Open a pull request against `dev` and fill in its template.

Security problems are not issues: see [SECURITY.md](SECURITY.md).
