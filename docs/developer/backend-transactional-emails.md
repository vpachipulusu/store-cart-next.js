# Transactional order emails (KAN-81)

Three emails go out through Resend ([ADR-009](../adr/0009-email-with-resend.md)), each queued with QStash:

| Kind | When | To |
|---|---|---|
| `order_confirmation` | the Connect webhook moves a checkout order to `paid` | the shopper (`customer_details.email` from the Checkout Session) |
| `new_order_alert` | same moment | every OWNER and ADMIN of the store's organisation with a verified email who has not turned off `email_notifications`, one message each |
| `order_shipped` | the merchant fulfils the order (`POST /v1/stores/{id}/orders/{order_id}/fulfil`) | the shopper |

Code: `app/services/order_email_job.py` (outbox writes, QStash publisher, runner),
`app/services/order_email_templates.py` (defaults, overrides, HTML), `app/repositories/order_emails.py` (store SQL),
`app/repositories/order_email_context.py` (platform reads), `app/api/v1/internal_order_emails.py` (QStash routes).
Configuration is reused, nothing new: `QSTASH_TOKEN`, `QSTASH_URL`, the QStash signing keys and
`PROVISIONING_BASE_URL` (as for store provisioning), `RESEND_API_KEY`, `EMAIL_FROM` and `APP_PUBLIC_URL`.

## Store schema (store migration 0012)

- `orders.customer_email`: nullable, 3 to 254 characters with an `@` after the first. Written once, in the
  transaction that moves the order to `paid`, from the Checkout Session (trimmed; refused rather than truncated when
  it would not fit the CHECK).
- `store_email_templates`: one optional row per kind (`kind` is the key) with `subject` (1 to 200 characters, no CR
  or LF) and `body_text` (1 to 10000). No row means the platform default. There is no write API yet (KAN-117).
- `order_emails` (the outbox): one row per order and kind (`UNIQUE (order_id, kind)`, cascade on order delete),
  `status` `pending`, `sent`, `skipped` or `failed`, `attempts`, and `sent_at` (set exactly when `sent`).

Expand-only: a store database still at 0011 keeps working. The email writes run in a SAVEPOINT, so on such a store
the payment or fulfilment commits as before and the backend logs `order email skipped`. Run `migrate_stores` after
deploying to bring every store to 0012.

## Flow

1. **Write.** The outbox rows are inserted (`ON CONFLICT DO NOTHING`) in the same store transaction as the status
   change: the confirmation and the alert only when `mark_checkout_paid` returns `PAID`; the shipped notice only when
   the fulfil `UPDATE` moved the order (a repeated fulfil is a 409 and writes nothing).
2. **Publish.** After the store commit, one QStash message per `pending` row to
   `{PROVISIONING_BASE_URL}/internal/order-emails/send`, body `{store_id, order_id, kind}` (ids only, never an
   address), `Upstash-Deduplication-Id: order-email-{store}-{order}-{kind}`, 3 retries, a failure callback, 3 s
   timeout.
   - Webhook: a publish failure raises, so the webhook answers 500 and Stripe redelivers. A delivery that finds the
     order already paid (`ALREADY_PAID`) re-publishes every confirmation or alert row still `pending`; this also
     covers a crash between the store commit and the platform event claim.
   - Fulfilment: a publish failure is logged (ids, kind, error class) and reported to Sentry; the merchant's request
     still succeeds and the row stays `pending`. There is no sweep job.
   - Without `QSTASH_TOKEN` and `PROVISIONING_BASE_URL` nothing is published (a warning is logged per row) and rows
     stay `pending`.
3. **Send.** `POST /internal/order-emails/send` (not in the OpenAPI schema; the `Upstash-Signature` JWT for this exact
   URL and body is the credential, as for the provisioning callbacks). It sends only a `pending` row:

   | Outcome | Row | Response |
   |---|---|---|
   | every message accepted | `sent` (conditional update) | 200 |
   | email disabled, no shopper address, no alert recipient, store gone | `skipped` | 200 |
   | Resend refused a message for good (4xx other than 408, 409, 429) | `failed`, reported to Sentry | 200 |
   | Resend error or timeout (5 s per message) | `attempts + 1`, stays `pending` | 500, QStash retries |
   | row not `pending` (already settled, or a duplicate delivery) | unchanged | 200, nothing sent |
   | body is not exactly `{store_id, order_id, kind}` | unchanged | 400 with `Upstash-NonRetryable-Error` |

   `POST /internal/order-emails/failed` is QStash's failure callback once the retries ran out: a row still `pending`
   becomes `failed` and is reported to Sentry.

Each message carries a Resend `Idempotency-Key` (`order-email-{store}-{order}-{kind}`, plus `-{user_id}` per alert
recipient), so a retry after a partial alert or a lost response does not deliver twice. The root `vercel.json`
rewrites `/internal/order-emails/(.*)` to the backend.

## Templates

Defaults live in code (`DEFAULT_TEMPLATES`), as `string.Template` text with a fixed variable list per kind:

| Kind | Variables |
|---|---|
| `order_confirmation` | `store_name`, `order_id`, `order_total`, `items` |
| `order_shipped` | `store_name`, `order_id`, `items`, `tracking_number`, `carrier` |
| `new_order_alert` | `store_name`, `order_id`, `order_total`, `items`, `order_url` |

- A store row wins. An unknown placeholder or bad syntax logs `store email template unusable` (kind and store id) and
  the default is used. `$$` is a literal dollar sign.
- The subject loses every control and line-separator character and is capped at 200 characters.
- HTML is built only by code: the rendered text (template and values) goes through `html.escape`, blank-line
  separated paragraphs become `<p>`, single newlines `<br>`, in a fixed layout. A store cannot add markup or links.
- The alert links to `{APP_PUBLIC_URL}/dashboard/orders/{order_id}` (escaped as an attribute); without
  `APP_PUBLIC_URL` there is no link.
- Money comes from integer minor units with the currency's ISO 4217 decimals (`JPY 1,500`, `BHD 1.234`,
  `GBP 25.50`).
- The platform `email_templates` table is not used.

## Privacy

Logs and Sentry events carry the store id, order id, kind and exception class names only: never an address, a
subject or a body (tests in `tests/services/test_order_email_job.py` and `tests/api/test_order_emails_e2e.py`
assert it). QStash payloads carry ids only.

## Tests

- Unit (no database): `tests/services/test_order_email_templates.py`, `test_order_email_job.py`,
  `test_merchant_order_emails.py`, `tests/services/test_email.py`, `tests/api/test_internal_order_emails.py`, the
  payment handler tests in `tests/services/test_store_checkout.py`. Fakes: `tests/fakes_email.py`.
- Real Postgres (`TEST_DATABASE_URL`, a local `*_test` database):
  `tests/services/test_store_order_emails_schema_e2e.py` (0012 CHECKs, cascade, 0011 fallback, downgrade) and
  `tests/api/test_order_emails_e2e.py` (webhook to send route, fulfilment, recipients, overrides, logs).

```bash
TEST_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:55481/kan81_test \
  uv run pytest tests/services/test_store_order_emails_schema_e2e.py tests/api/test_order_emails_e2e.py
```
