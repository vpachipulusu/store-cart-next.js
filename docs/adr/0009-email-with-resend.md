# ADR-009: Email through Resend from the backend

- **Status:** Proposed
- **Date:** 2026-10-11
- **Plan decisions:** D22 (email)
- **Jira:** KAN-29; carried out in KAN-30 and E3

## Context

The boilerplate sends email through Resend from the Next.js server. The template sends email with
fastapi-mail and Jinja templates in `email_templates/`. Foundation's definition of done says the frontend
holds no server secrets, and the Resend API key is one of them.

## Decision

- Keep **Resend** as the only email provider (D22). Remove fastapi-mail and the template's `email_templates/`.
- Send email **from the backend**, through one email service in `services/` that calls Resend over HTTPS. The
  Resend API key lives only in the backend environment.
- Firebase still sends its own authentication emails (verification, password reset) where the boilerplate
  relies on it today.
- Per-store email templates and branding are not part of Foundation; they are redesigned in E22 (KAN-114).

## Alternatives considered

- **Keep sending from Next.js.** Leaves a server secret in the frontend, which goes against the Foundation
  definition of done.
- **fastapi-mail over SMTP (the template).** Adds SMTP credentials and a second provider for no gain.
- **Postmark or SES.** No compelling advantage over a provider already set up and working.

## Consequences

- One provider, one key, held in one place.
- Emails that must go out after a request finishes (for example order confirmations later) are sent through
  QStash jobs ([ADR-002](0002-hosting-on-vercel.md)), not in-process background tasks.
