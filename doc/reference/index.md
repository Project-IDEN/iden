# Reference

Lookup material. Nothing here explains *why* — that is [Concepts](../concepts/index.md).

- **[Endpoints](endpoints.md)** — every route, generated from the application.
- **[Scopes](scopes.md)** — the permissions IDEN defines for itself.
- **[Token claims](claims.md)** — what is in each kind of token.
- **[Configuration](configuration.md)** — every setting, and the three that matter in production.
- **[Data model](data-model.md)** — tables, relationships, and the constraints worth knowing.
- **[Errors](errors.md)** — the error shapes and what each status means.

!!! tip "The live version is better"
    A deployment running with `IDEN_ENV=dev` — a laptop, or the provider from source — serves
    interactive API documentation at `/docs`, generated from the same code. Production withholds it. It has request and response bodies, required permissions, and a working "try it" button.
    Use it when you are actually integrating; use these pages when you are reading.
