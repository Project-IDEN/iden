# Security

IDEN is a university capstone project, not production software. It has been reviewed by the people
who built it, not audited by anyone else. See [Known Limitations](README.md#known-limitations) before
running it anywhere that matters.

## Reporting a vulnerability

Report it privately, through GitHub: the repository's **Security** tab, then **Report a
vulnerability**. Please do not open a public issue or pull request for it.

Say what you found, how to reproduce it, and what it lets an attacker do. We will acknowledge it and
tell you what we intend to do; as a student project, we cannot promise a time.

## What is in scope

The provider, the biometric engine, the kiosk server and app, the two web frontends, and the
deployment files in this repository. Weaknesses already listed under Known Limitations or in
[Open issues](doc/roadmap.md#open-issues) are known; a way to exploit one that goes further than it
says is still worth reporting.

How IDEN is meant to be deployed safely is in the
[Security checklist](doc/operations/security-checklist.md).
