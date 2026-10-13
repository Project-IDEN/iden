# Consent

Consent answers a narrow question: *is this application allowed to act on your behalf, with these
permissions?*

It is not about whether Sarah may read attendance records — that is her permissions, and no amount of
agreeing changes it. It is about whether the *library app* may do so **as her**.

## When someone is asked

IDEN asks the first time an application requests permissions the person has not already agreed to
give it, and records the answer so they are not asked again.

Applications marked `skipConsent` never ask. That flag is for **first-party** applications — your own
dashboard, your own intranet. Asking your own staff to consent to your own dashboard is noise that
teaches people to click through prompts without reading them, which is the exact habit consent
screens depend on not existing.

Everything else should ask.

## What the screen shows

The application's name and, when it has one, its logo; then every permission it is asking for, each
in words and by its scope value. The permissions are the content — the screen exists to make the
request legible before it is granted.

The name and logo are what the application's registrant chose. They identify an application people
already know; they do not vouch for one they do not. See
[Let people register their own applications](../guides/self-service-registration.md#limits-worth-knowing).

## What gets recorded

The permissions **actually granted**, not the ones requested.

This distinction is not cosmetic. Suppose the library app asks for `library:loans:read` and
`library:admin`, and Sarah holds only the first. She is shown, and agrees to, the first. If IDEN
recorded the raw request, `library:admin` would be marked as consented — and the day someone gives
Sarah that permission, the library app would receive it without anyone ever being asked.

Consent covers what someone was shown. Nothing else.

## Withdrawing it

`GET /entity/connections` lists the applications a person has granted access to, and
`DELETE /entity/connections/{clientId}` takes it back — deleting the agreement and revoking every
refresh token that application holds for them.

Access tokens already issued run to their expiry, as always.

Withdrawing is not a block list. The application may ask again — and will have to, since the record
is gone.

!!! note "First-party applications do not appear here"
    They never asked, so there is no agreement to withdraw. To cut one off, an administrator changes
    what it may request.
