# Development setup

See [Run it locally](../guides/quickstart.md) for the environment. This page is about working on the
code.

## The scripts

Four, all run from `provider/` as `uv run python -m scripts.<name>`.

| Script | Does |
|---|---|
| `gen_keys` | Writes a date-stamped RSA signing key and, beside it, `totp.key` — which encrypts TOTP secrets at rest. Refuses to overwrite either. |
| `seed` | Upserts the system catalogue and the bootstrap clients and administrator. Idempotent, and refuses to run against an unmigrated database. |
| `reset` | Drops the schema, flushes Redis, migrates, and seeds. Asks first; `--yes` skips the prompt. Refuses when `IDEN_ENV=prod`. |
| `cleanup` | Deletes expired authorization codes and refresh tokens. `--dry-run` counts instead. Meant for a schedule — see [Deployment](../operations/deployment.md#housekeeping). |

`reset` flushes Redis as well as dropping the schema, and that is the part people forget doing it by
hand: sessions outlive the rows they point at, so a database-only reset leaves live cookies naming
users who no longer exist, and the next request fails in a way that looks like a bug rather than a
stale login.

## The checks

All four run from `provider/`, and all four are expected to be clean:

```bash
uv run ruff format .    # formatting, 88 columns
uv run ruff check .     # lint: E, F, I, UP, B
uv run pyright          # types, standard mode
uv run pytest           # the suite
```

The first three run automatically on commit. Install the hook once per clone, from the repository
root:

```bash
uv run --project provider pre-commit install
```

It checks **staged content only** — unstaged work is stashed first — so what is checked is what is
being committed. A hook that rewrites a file fails the commit: stage the result and commit again.

`pytest` is deliberately **not** in the hook. It needs PostgreSQL and Redis running and takes about
twenty seconds; a gate that fails because Docker is down teaches people to reach for `--no-verify`,
and a hook everyone bypasses is worse than no hook.

## Two disabled lint rules

Both have their reasoning next to them in `pyproject.toml`:

- **`E501`** (line too long) — the formatter owns line length and will not split a string or a
  comment, so this only ever reports lines ruff itself chose to leave.
- **`B008`** (call in argument default) — `Depends(require_scope(...))` is the FastAPI idiom. B008
  exists to catch mutable defaults, which this is not.

## Type checking

`typeCheckingMode` is pinned to `standard` so an editor set to `strict` agrees with what runs here.

Strict is not a useful bar on a pytest suite: fixtures arrive as unannotated parameters, and each
unknown type cascades through every use of it — about two thousand findings that say nothing about
the tests. Clearing it honestly would mean annotating some four hundred and seventy parameters.

## Adding a dependency

```bash
cd provider
uv add <package>            # runtime
uv add --dev <package>      # tooling
```

Never hand-edit the dependency lists — `uv` owns them and the lockfile.

## Working on these docs

```bash
# From the repository root. Port 8001, because the provider itself uses 8000.
uv run --project provider mkdocs serve -a localhost:8001
```

Live reload at <http://localhost:8001>. The site lives at the repository root rather than under
`provider/` because it will grow sections for the kiosk, the engine, and the front ends.

```bash
uv run --project provider mkdocs build --strict
```

`--strict` turns broken internal links into failures, which is what you want before pushing.

## How the site is published

`.github/workflows/docs.yml` builds on every pull request that touches `doc/` and publishes to
[GitHub Pages](https://yephonekyaw.github.io/iden/) when those changes reach **`dev`**, which is
where work lands — so the published site tracks the code rather than the last release.

Pull requests build but do not publish, so a broken link fails the check before it is merged rather
than after it is live. Nothing is committed to a `gh-pages` branch — the built site is uploaded as an
artifact and deployed from it, so the repository history stays free of generated files.
