# Measuring performance

How fast IDEN is on your hardware, and how much it takes before it slows down. Three tools, one per
question:

| Question | Tool | Runs where |
|---|---|---|
| How long does the engine take over one capture, stage by stage? | `engine/scripts/bench.py` | The engine's machine, from `engine/` |
| How much traffic does a running provider or engine sustain, and where does it break? | `perf/loadtest.py` | Any machine with [uv](https://docs.astral.sh/uv/), ideally not the one under test |
| A person's access token for the load test's signed-in scenarios | `provider/scripts/mint_token.py` | The provider's host |

There is no load test for the kiosk server. It serves one browser on one device, and an enrolment
it relays costs what the same capture costs the provider and the engine, which the load test
measures directly.

!!! warning "Only against a deployment you own"
    A stress test is built to push a server past what it can handle. Point it at a staging copy, or
    at production during a window when nobody needs to sign in.

## The engine, without HTTP

On the engine's machine, from `engine/`, with the models fetched:

```bash
uv run python -m scripts.bench
uv run python -m scripts.bench --runs 50 --device cuda --json bench.json
```

It sends nine frames of one photo at the kiosk's 640×480 through each stage, and then through a
whole enrolment and a whole sign-in. `--image` uses a photo of your own instead of the bundled
test image; it must show one face. For example, on an Apple M4 laptop's CPU:

```text
Model buffalo_l-liveness-1 on cpu (Darwin arm64, 10 cores), 10 runs

| Stage                         | mean ms | p50 ms | p95 ms | min ms |
|-------------------------------|--------:|-------:|-------:|-------:|
| decode (9 frames)             |    10.5 |   10.4 |   10.9 |   10.3 |
| detect (9 frames, one by one) |   365.3 |  366.8 |  376.2 |  355.2 |
| embed (batch of 9)            |   238.8 |  240.4 |  246.1 |  229.7 |
| anti-spoofing (batch of 5)    |     4.0 |    4.0 |    4.6 |    3.6 |
| enrol, end to end             |   525.1 |  526.7 |  529.2 |  519.1 |
| verify, end to end            |   335.7 |  335.8 |  342.5 |  330.6 |
```

Almost all of the time goes to the two neural networks, detection and embedding. Decoding and the
Python around the models are a few percent. *Enrol, end to end* is less than detection and
embedding added up because the engine detects four frames at once; the *detect* row runs them one
at a time for comparison.

This is the number to compare a CPU with a GPU on, or one model with another. For what users will
actually experience, add the network and the provider's own work with the load test below.

## Load-testing over HTTP

```bash
uv run perf/loadtest.py <scenario> [--mode load|stress|spike|soak] [--url URL] [options]
```

uv installs the script's one dependency on the first run. `--url` defaults to
`http://localhost:8000`, where the Docker deployment publishes the provider.

### Scenarios

| Scenario | Request | What it measures | Needs |
|---|---|---|---|
| `discovery` | `GET /.well-known/openid-configuration` | The framework, middleware and one small query. A baseline. | — |
| `jwks` | `GET /.well-known/jwks.json` | The same, with no database at all. | — |
| `sessions` | `GET /entity/sessions` | A signed-in request: token check, account lookup, revocation check, and the person's sessions from Redis. | `--token` |
| `permissions` | `GET /entity/permissions` | A signed-in request that also loads the person's groups, roles and scopes and works out where each permission comes from. | `--token` |
| `token` | `POST /oauth2/token`, `client_credentials` | Client authentication, which is argon2 and costs 64 MiB and real CPU every time. | `--client-id`, `--client-secret` |
| `engine-verify` | `POST /verify` on the engine | One face sign-in: three frames, detection, anti-spoofing and a match. | `--url` of the engine; `--token` with its token if it has one |

**A token for `sessions` and `permissions`.** On the provider's host:

```bash
docker compose exec -e EMAIL=admin@example.com provider python -m scripts.mint_token
# from source, in provider/:
EMAIL=admin@example.com uv run python -m scripts.mint_token
```

It prints an access token for that person, valid for an hour (`TTL=` in seconds changes that).
Signing in through the browser for every virtual user would measure the sign-in, not the route.
The token is a real credential for that person until it expires, so treat it like one.

**A client for `token`.** Register a machine client in the dashboard and pass its id and secret
(`IDEN_CLIENT_SECRET` in the environment keeps the secret out of your shell history). The token
endpoint allows 120 requests a minute from one address, so a load test against it measures the rate
limiter unless you set `IDEN_RATE_LIMIT_ENABLED=false` in `deploy/.env` and restart the provider,
for the duration of the test only. A run that hits the limit says so.

**Reaching the engine.** On the provider's host the engine publishes no port. Measure it where it
runs on a machine of its own (`engine/deploy/`, which publishes `ENGINE_PUBLISH`, 8000 by default),
or start it from source on the machine you are sizing:

```bash
cd engine && uv run uvicorn engine.app:app --port 8001
uv run perf/loadtest.py engine-verify --url http://localhost:8001
```

The scenario first asks the engine to embed the photo, then compares every capture against that
template, so each request is a successful, live match: the full cost of a real sign-in.

### Modes

| Mode | What it does | Answers |
|---|---|---|
| `load` (default) | `--concurrency` users for `--duration` seconds. | What the server sustains at a given load. |
| `stress` | Starts at `--start` users and doubles every `--duration` seconds, up to `--max`, stopping at the first step whose error rate passes `--max-errors` (default 1%) or whose p99 passes `--max-p99` ms (default 1000). | How much it takes before the server degrades. |
| `spike` | `--concurrency` users, then `--spike` users, then `--concurrency` again, `--duration` seconds each. | Whether a sudden crowd is absorbed, and whether the server recovers afterwards. |
| `soak` | `--concurrency` users for a long `--duration`, reported every `--interval` seconds. | Whether it degrades over time: latency that creeps up over an hour is a leak or a growing table. |

Every mode first runs a five-second warm-up that is not counted (`--warmup`), and before that sends
a single request, so a wrong URL or token stops the run with the server's answer instead of
producing thirty seconds of errors. `--json results.json` also writes every number, with the
time and the machine it ran from.

### Reading the results

A `stress` run of `engine-verify` against the engine on the same M4 laptop's CPU:

```text
| Phase | Users | Requests | Req/s | Errors | p50 ms | p90 ms | p99 ms | max ms |
|-------|------:|---------:|------:|-------:|-------:|-------:|-------:|-------:|
| x1    |     1 |       36 |   4.4 |   0.0% |  228.6 |  232.6 |  238.9 |  238.9 |
| x2    |     2 |       42 |   5.1 |   0.0% |  387.0 |  429.6 |  456.1 |  456.1 |
| x4    |     4 |       43 |   5.0 |   0.0% |  786.6 |  892.3 | 1038.5 | 1038.5 |
| x8    |     8 |       47 |   5.1 |   0.0% | 1550.4 | 1652.0 | 1858.9 | 1858.9 |
| x16   |    16 |       54 |   5.0 |   0.0% | 3171.1 | 3283.7 | 3518.1 | 3518.1 |
```

- **Capacity is where Req/s stops rising.** Here that is about five sign-ins a second, reached at
  two users. Past it, more users add no throughput, only waiting.
- **Users ≈ Req/s × latency.** Once throughput is flat, every user you add makes everyone wait
  longer: twice the users, twice the p50. Nothing failed, but a person signing in among sixteen
  others waits three seconds. A queue that keeps growing ends in timeouts.
- **Watch p99, not the mean.** The slowest one in a hundred is what someone in a busy hour feels.
- **The test is closed-loop.** Each virtual user sends its next request when the last one is
  answered, so a slow server also slows the arrival of new requests. Real users do not wait for each
  other, so under overload real latency is worse than this test shows, never better.
- **If the report says the load generator was CPU-bound,** the numbers show the limit of the
  machine running the test, not of the server. Run it from another machine, or run several copies
  and add their Req/s together. One Python process manages a few thousand requests a second, more
  than enough for the signed-in scenarios, the token endpoint and the engine, but possibly not for
  `jwks` on a fast server.

### What to change when it is not enough

| Bottleneck | Sign | Lever |
|---|---|---|
| Engine | `engine-verify` flattens at a few Req/s | A GPU first ([On an NVIDIA GPU](biometric-engine.md#on-an-nvidia-gpu)); then `IDEN_ENGINE_WORKERS`, which on a CPU only helps while cores are idle |
| Provider CPU | `sessions` or `permissions` flatten while the provider's container is at 100% of a core per worker | `IDEN_WORKERS`, about 300 MiB each |
| argon2 | `token` flattens near what four hashes at a time allow: about 170 Req/s per worker on an M4, often less on a server core | `IDEN_WORKERS`; each worker hashes four at a time at most, so a flood queues rather than exhausting memory |
| PostgreSQL or Redis | Every signed-in scenario degrades together while the provider is not at full CPU | The store's own resources |

## Keeping the numbers

A number without its hardware means nothing. Keep the `--json` output together with the commit it
was measured at (`git rev-parse --short HEAD`), the machine the server ran on, `IDEN_WORKERS` and
`IDEN_ENGINE_WORKERS`, and whether the engine was on a CPU or a GPU. Then run the same commands
before and after a change to see what it bought.
