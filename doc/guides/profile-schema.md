# Define your profile schema

The fields your organization actually collects. See [Profile fields](../concepts/profile-fields.md)
for why this is defined at runtime rather than shipped.

!!! tip "Prefer the dashboard?"
    Everything here is also in the dashboard, under **Administration → Profile fields**.
    `$ADMIN_TOKEN` in the examples is an administrator's access token — [how to get
    one](index.md#calling-the-admin-api-yourself).

## Start from a preset

IDEN ships no profile fields, but it does ship a catalogue of the ones most
organizations end up defining — with the type, validators and permissions already
decided.

```bash
curl http://localhost:8000/admin/profile-fields/presets \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Nothing there exists until you create it. Each entry is shaped so it can be posted
straight back to `POST /admin/profile-fields`, with anything you like changed
first.

What they are actually for is `userWritable`. Who owns a piece of data is the
question that is easy to get wrong, and each preset answers it and says why:
`preferred_name` belongs to its owner, `student_id` belongs to the registrar.

## A field the organization owns

A student number: set by the registrar, visible to the student, not editable by them, and unique.

```bash
curl -X POST http://localhost:8000/admin/profile-fields \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "key": "student_id",
    "label": "Student number",
    "dataType": "string",
    "required": true,
    "unique": true,
    "userReadable": true,
    "userWritable": false,
    "validators": {"pattern": "^[0-9]{8}$"},
    "displayOrder": 10
  }'
```

## A field the person owns

```bash
curl -X POST http://localhost:8000/admin/profile-fields \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "key": "preferred_name",
    "label": "Preferred name",
    "userWritable": true,
    "displayOrder": 20
  }'
```

The only difference that matters is `userWritable`. It decides which endpoint can write the value:

| | `PATCH /entity/profile` | `PATCH /admin/users/{id}/profile` |
|---|---|---|
| `userWritable: true` | :material-check-circle-outline: | :material-check-circle-outline: |
| `userWritable: false` | :material-close-circle-outline: `422` | :material-check-circle-outline: |

## A field only some people have

Bind it to a group and it applies only to members. The same `POST /admin/profile-fields` as above,
with this body:

```bash
-d '{"key": "enrollment_year", "label": "Year of enrolment",
     "dataType": "integer", "groupId": "<Students group id>",
     "validators": {"min": 1900, "max": 2100}}'
```

Staff never see it. Students see it in `GET /entity/profile/schema`, and a dashboard renders the form
from that response rather than hardcoding your fields into a general-purpose identity provider.

## Releasing a field to applications

By default, no application ever sees a custom field. To release one, create it with a claim name and
the permission that releases it:

```bash
-d '{"key": "department", "label": "Department",
     "claimName": "department", "claimScope": "profile"}'
```

Now `department` appears in ID tokens and `/oauth2/userinfo` — but only for applications granted the
`profile` permission. Both `claimName` and `claimScope` are required together: a claim with no
permission attached would go to everyone.

Reserved OIDC names (`sub`, `iss`, `aud`, `acr`, `sid`, …) are refused, so a custom field cannot
shadow a claim a token's meaning depends on.

## Setting values

=== "As the person"

    With the person's own access token, as their application would send it.

    ```bash
    curl -X PATCH http://localhost:8000/entity/profile \
      -H "Authorization: Bearer $USER_TOKEN" -H "Content-Type: application/json" \
      -d '{"fields": {"preferred_name": "Sam"}}'
    ```

=== "As an administrator"

    ```bash
    curl -X PATCH http://localhost:8000/admin/users/{id}/profile \
      -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
      -d '{"fields": {"student_id": "12345678"}}'
    ```

Writing a field you may not write is refused with `422`, not ignored — an application should never
believe it saved something it did not.

## What cannot be changed later

`key`, `dataType`, `unique` and `groupId` are absent from the update endpoint on purpose. Each would
rewrite the meaning of values already stored: changing a type cannot recast them, and adding
`unique` to a field that already has duplicates cannot succeed.

Define a new field instead.

!!! warning "Deleting a field deletes every answer to it"
    That is the point — an organization that stops collecting something should stop holding it — but
    there is no undo.
