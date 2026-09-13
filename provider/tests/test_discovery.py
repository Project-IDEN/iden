async def test_metadata_advertises_only_the_supported_grants(client, catalogue):
    body = (await client.get("/.well-known/openid-configuration")).json()

    assert body["grant_types_supported"] == [
        "authorization_code",
        "refresh_token",
        "client_credentials",
    ]
    assert body["response_types_supported"] == ["code"]


async def test_only_s256_pkce_is_advertised(client, catalogue):
    body = (await client.get("/.well-known/openid-configuration")).json()
    assert body["code_challenge_methods_supported"] == ["S256"]


async def test_scopes_are_read_from_the_database(client, catalogue):
    """Not a hard-coded list: admins define scopes at runtime, so discovery has
    to reflect whatever is in the database right now."""
    body = (await client.get("/.well-known/openid-configuration")).json()

    assert "admin:users:read" in body["scopes_supported"]
    assert {"openid", "profile", "email", "offline_access"} <= set(
        body["scopes_supported"]
    )
    assert len(body["scopes_supported"]) == len(catalogue["scopes"]) + 4


async def test_a_new_scope_appears_without_a_restart(client, catalogue, db):
    from provider.shared.models import Scope

    api_id = catalogue["scopes"]["admin:users:read"].api_id
    db.add(
        Scope(
            api_id=api_id, value="attendance:records:read", description="Read records."
        )
    )
    await db.commit()

    body = (await client.get("/.well-known/openid-configuration")).json()
    assert "attendance:records:read" in body["scopes_supported"]


async def test_jwks_exposes_a_kid_per_key(client):
    body = (await client.get("/.well-known/jwks.json")).json()

    assert body["keys"]
    for key in body["keys"]:
        assert key["kid"] and key["kty"] == "RSA" and key["use"] == "sig"


async def test_jwks_never_leaks_private_material(client):
    body = (await client.get("/.well-known/jwks.json")).json()
    for key in body["keys"]:
        assert not {"d", "p", "q", "dp", "dq", "qi"} & set(key)


async def test_metadata_advertises_the_session_controls(client, catalogue):
    """A conforming client will not attempt any of this without being told."""
    body = (await client.get("/.well-known/openid-configuration")).json()

    assert set(body["prompt_values_supported"]) == {
        "none",
        "login",
        "consent",
        "select_account",
    }
    assert body["backchannel_logout_supported"] is True
    assert body["backchannel_logout_session_supported"] is True
    assert body["end_session_endpoint"].endswith("/oauth2/logout")
    assert "sid" in body["claims_supported"]


async def test_only_levels_a_registered_method_reaches_are_advertised(
    client, catalogue
):
    """`iden:loa:3` needs a face, and nothing registers one yet. Advertising it
    invites a request that can only ever be refused."""
    body = (await client.get("/.well-known/openid-configuration")).json()

    assert body["acr_values_supported"] == ["iden:loa:1", "iden:loa:2"]
