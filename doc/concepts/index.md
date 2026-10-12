# Concepts

Identity systems are mostly vocabulary. The mechanisms underneath are not complicated, but almost
every word — *scope*, *claim*, *audience*, *grant* — means something narrower than it sounds. These
pages introduce them in the order that makes each one make sense.

Read them in order the first time.

1. **[Identity and access](identity-and-access.md)** — the five nouns the whole system is built
   from, and how a person ends up with permissions.
2. **[Tokens](tokens.md)** — what IDEN hands out, what each kind is for, and why applications must
   never confuse them.
3. **[Sessions and single sign-on](sessions.md)** — how one sign-in becomes access to every
   application, and how signing out reaches all of them.
4. **[Assurance and step-up](assurance.md)** — how strongly someone proved who they are, and how an
   application demands more.
5. **[Faces](biometrics.md)** — a face as a second factor: enrolled at a kiosk, checked for
   liveness, compared one to one.
6. **[Consent](consent.md)** — what an application is allowed to ask for on someone's behalf.
7. **[Profile fields](profile-fields.md)** — how an organization defines what it collects about
   people.
8. **[The audit log](audit.md)** — what is recorded, and what that record is for.

## The shortest possible summary

A **person** signs in and gets a **session**. An **application** sends them to IDEN and receives a
**token**. That token carries **permissions**, which the person holds because an administrator gave
them — directly, or through a **role**, or through a **group**. Your own **API** reads the token and
decides what to allow.

Everything else is detail about how each of those is proved, limited, revoked, and recorded.
