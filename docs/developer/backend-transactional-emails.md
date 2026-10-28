# Transactional order emails (KAN-81)

Three emails go out through Resend ([ADR-009](../adr/0009-email-with-resend.md)), each queued with QStash:

| Kind | When | To |
|---|---|---|
| `order_confirmation` | the Connect webhook moves a checkout order to `paid` | the shopper (`customer_details.email` from the Checkout Session) |
| `new_order_alert` | same moment | every OWNER and ADMIN of the store's organisation with a verified email who has not turned off `email_notifications`, one message each |
| `order_shipped` | the merchant fulfils the order (`POST /v1/stores/{id}/orders/{order_id}/fulfil`) | the shopper |

Code: `app/services/order_email_job.py` (jobs, QStash publisher), `app/services/order_email_record.py` (the writes
in the order's transaction), `app/services/order_email_runner.py` (sending one row),
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

Expand-only: a store database still at 0011 keeps working. The `orders.customer_email` CHECK is added `NOT VALID` and
validated in the same revision (as 0005 does), so the ADD takes only a brief lock. Run `migrate_stores` after deploying
to bring every store to 0012.

The email writes run in a SAVEPOINT inside the order's transaction, and a failure there is classified by SQLSTATE:

| SQLSTATE | Meaning | What happens |
|---|---|---|
| 42P01, 42703 | the store has not reached 0012 | skipped, `order email skipped` logged; outside local/test also a Sentry event (a typo in a column name would otherwise switch every email off silently) |
| 40001, 40P01, 55P03, 57014; classes 08, 53, 57P; or no SQLSTATE at all | transient (serialization, deadlock, lock or statement timeout, connection, resources, admin shutdown, a dropped connection) | raised as `OrderEmailFailed`: the payment or fulfilment rolls back and is retried (Stripe redelivers) |
| any other, deterministic SQLSTATE (42501, 23xxx, ...) | an unexpected failure | reported to Sentry once (logged as a warning) and skipped: the payment still confirms (an unrecorded payment is worse than a missing email) |

A raw SQLAlchemy error never leaves the module: its text carries the statement parameters, which include the shopper's
address. Only the class name and SQLSTATE are logged or reported.

## Flow

1. **Write.** The outbox rows are inserted (`ON CONFLICT DO NOTHING`) in the same store transaction as the status
   change: the confirmation and the alert only when `mark_checkout_paid` returns `PAID`; the shipped notice only when
   the fulfil `UPDATE` moved the order (a repeated fulfil is a 409 and writes nothing).
2. **Publish.** After the store commit, one QStash message per `pending` row to
   `{PROVISIONING_BASE_URL}/internal/order-emails/send`, body `{store_id, order_id, kind}` (ids only, never an
   address), `Upstash-Deduplication-Id: order-email-{store}-{order}-{kind}`, 3 retries, a failure callback, 3 s
   timeout.
   - Webhook: a publish failure that a retry can fix (timeout, network error, QStash 5xx or 429) raises, so the
     webhook answers 500 and Stripe redelivers. A delivery that finds the order already paid (`ALREADY_PAID`)
     re-publishes every confirmation or alert row still `pending`; this also covers a crash between the store commit
     and the platform event claim. Publishing happens inside the platform claim on purpose (held for at most the 3 s
     timeout; the jobs are published concurrently).
   - QStash refusing the request itself (any other 4xx: a bad token or destination) is a misconfiguration: it is
     logged and reported to Sentry, never a 500, so it cannot fail every Connect webhook for days. The webhook
     answers 200, so the row stays `pending` until a sweeper exists (there is none yet; see below).
   - Fulfilment: a publish failure is logged (ids, kind, error class) and reported to Sentry; the merchant's request
     still succeeds and the row stays `pending`. There is no sweep job.
   - Without `QSTASH_TOKEN` and `PROVISIONING_BASE_URL` nothing is published and rows stay `pending`: a warning in
     local/test, an error and a Sentry event elsewhere.
3. **Send.** `POST /internal/order-emails/send` (not in the OpenAPI schema; the `Upstash-Signature` JWT for this exact
   URL and body is the credential, as for the provisioning callbacks). It sends only a `pending` row:

   | Outcome | Row | Response |
   |---|---|---|
   | every message accepted | `sent` (conditional update) | 200 |
   | email disabled, no shopper address, no alert recipient, store gone | `skipped` | 200 |
   | Resend refused a message for good (a 4xx other than 401, 403, 408, 409, 429; 422 is the usual one) | `failed`, reported to Sentry | 200 |
   | Resend error or timeout (5 s per message), or 401/403 (a key or sender domain the operator can fix) | `attempts + 1`, stays `pending`; logged only | 500, QStash retries |
   | row not `pending` (already settled, or a duplicate delivery) | unchanged | 200, nothing sent |
   | body is not exactly `{store_id, order_id, kind}` | unchanged | 400 with `Upstash-NonRetryable-Error` |

   `POST /internal/order-emails/failed` is QStash's failure callback once the retries ran out: a row still `pending`
   becomes `failed` and is reported to Sentry. Retryable failures reach Sentry only then, once.

   The alert goes to at most `MAX_ALERT_RECIPIENTS` (20) members, all sent concurrently with the 5 s timeout each;
   the number dropped is logged (ids only). Any transient failure retries the whole alert (the per-recipient keys
   make resending an accepted message a no-op). One recipient refused for good leaves the row `failed` even when the
   others got theirs. When two deliveries race, only one settles the row; the other logs and returns the row's
   actual state.

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
- The subject loses every control and line-separator character and is capped at 200 characters. Line breaks in
  merchant text (product names, variant labels, tracking number, carrier, store name) become single spaces before
  they are substituted.
- HTML is built only by code: the rendered text (template and values) goes through `html.escape`, blank-line
  separated paragraphs become `<p>`, single newlines `<br>`, in a fixed layout. A store cannot add markup or links.
- The alert links to `{APP_PUBLIC_URL}/dashboard/orders/{order_id}` (escaped as an attribute); without
  `APP_PUBLIC_URL` there is no link. Known limitation: the dashboard opens the order in the store currently selected,
  so a member of an organisation with several stores may need to switch to the store the alert names first (a 404
  otherwise). A frontend story to carry the store in the link is with the owner.
- Money comes from integer minor units with the currency's ISO 4217 decimals (`JPY 1,500`, `BHD 1.234`,
  `GBP 25.50`).
- The platform `email_templates` table is not used.

## Known limits and notes

- **Abuse (for KAN-117).** Once merchants can write templates, the store's own text goes out from the platform's
  sending domain. Before that ships, add per-store and per-address send limits and a fixed platform footer.
- **Erasure.** `orders.customer_email` is personal data: future order or customer erasure work must cover it.
- **Alert eligibility** uses the synced `users.email_verified` flag on the platform database.
- **Resend idempotency (not handled).** Resend answers 422 when an idempotency key is reused with a changed payload
  (for example a template edited between a failed send and its retry); the row then becomes `failed`.
- **`attempts`** is informational only: QStash owns the retry count (`ORDER_EMAIL_RETRIES`).
- **No sweeper.** Rows left `pending` stay pending: after a fulfilment whose publish failed, after QStash refused a
  publish (bad token or destination; the webhook answered 200), or while QStash is not configured. A sweep job that
  re-publishes old `pending` rows is future work.

## Privacy

Logs and Sentry events carry the store id, order id, kind and exception class names only: never an address, a
subject or a body (tests in `tests/services/test_order_email_runner.py`, `test_order_email_record.py` and
`tests/api/test_order_emails_e2e.py` assert it). QStash payloads carry ids only.

## Tests

- Unit (no database): `tests/services/test_order_email_templates.py`, `test_order_email_job.py`,
  `test_order_email_record.py`, `test_order_email_runner.py`, `test_merchant_order_emails.py`, `tests/services/test_email.py`, `tests/api/test_internal_order_emails.py`, the
  payment handler tests in `tests/services/test_store_checkout.py`. Fakes: `tests/fakes_email.py`.
- Real Postgres (`TEST_DATABASE_URL`, a local `*_test` database):
  `tests/services/test_store_order_emails_schema_e2e.py` (0012 CHECKs, cascade, 0011 fallback, downgrade) and
  `tests/api/test_order_emails_e2e.py` (webhook to send route, fulfilment, recipients, overrides, logs).

```bash
TEST_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:55481/kan81_test \
  uv run pytest tests/services/test_store_order_emails_schema_e2e.py tests/api/test_order_emails_e2e.py
```
