# Testing

The suite runs against a **real PostgreSQL database** (`iden_test`), created once per session and
truncated between tests, and Redis logical database 15, flushed around every test.

Not SQLite. The models use PostgreSQL arrays, UUIDs, JSONB, and partial indexes, and a test that
passes on a different engine than production proves less than it appears to.

```bash
uv run pytest
uv run pytest tests/test_sso.py -v
uv run pytest -k "refresh and not concurrent"
```

The suite is about correctness. How fast IDEN is, and how much load it takes, is measured against a
running deployment instead: see [Measuring performance](../operations/performance.md).

## The fixtures worth knowing

| Fixture | Gives you |
|---|---|
| `client` | The app, driven in-process over ASGI. No server, no port. |
| `db` | A session for the test body. Routes get their own — they commit, and the test must see it. |
| `catalogue` | Permissions and roles, seeded through the **real** functions in `scripts/seed.py`. |
| `admin_user`, `member` | A full administrator, and an ordinary person. |
| `dashboard`, `kiosk`, `third_party` | A public client, a machine client, and one that must ask for consent. |
| `token_for(*scopes)` | A token carrying exactly those permissions — assert on authorization without running a sign-in. |
| `stale_headers` | A token whose sign-in is an hour old, for freshness tests. |

`catalogue` seeding through the real seed functions is deliberate: drift between the seed and the
tests surfaces as a failure rather than as a surprise in production.

## The rule that matters most

**A regression test must be shown to fail without its fix.**

This is not a formality. Two concurrency tests in this repository once passed with the fix reverted —
they used `asyncio.gather` over HTTP, and were passing on timing luck. They would have certified a
live race as fixed.

The habit that catches it: revert the fix, watch the test fail, restore the fix, watch it pass. Every
fix commit here records that it was done.

A related trap, from the same area: a test that passes in isolation and fails under full-suite load
is telling you something real. The refresh-lock gap was found exactly that way.

## Writing a good one here

**Name the behaviour, not the mechanism.** `test_a_read_only_field_is_refused` beats
`test_patch_returns_422`.

**Say why in the docstring** when the reason is not obvious from the name:

```python
async def test_the_right_password_still_works_under_attack(self, client):
    """The reason failures are counted rather than attempts: otherwise anyone
    could lock anyone else out by guessing badly on purpose."""
```

**Assert the consequence, not the implementation.** For a revoked session, assert that refreshing
fails — not that a particular column changed.

**Prefer determinism to timing.** Rather than sleeping past a window, mint a token with an old
`auth_time`. Rather than racing two requests and hoping, hold one transaction open and assert the
other blocks.
