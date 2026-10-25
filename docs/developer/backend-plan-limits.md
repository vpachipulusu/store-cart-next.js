# Plan limits on create (KAN-84)

The numbers live in `fastapi_backend/app/core/plans.py` (`PLANS`; `None` is unlimited). Every limit is enforced where the
resource is created, in the same transaction as the insert, and refused with **409** and a message that names the plan and
says to upgrade. Messages are built in `app/services/plan_limits.py` and hold no store data.

| Limit | Scope | Enforced in | Status |
|---|---|---|---|
| `max_stores` | organisation (archived stores do not count) | `OrganizationsService.create_store`, under the organisation row lock (KAN-45) | done |
| `max_products` | **per store**, drafts included | `StoreProductsService.create` (`POST /v1/stores/{store_id}/products`) | done (KAN-84) |
| `max_staff` | organisation, every membership counts (owner included) | `InvitationsService` create and accept, under the organisation row lock (`require_staff_capacity`) | done (KAN-62) |

## Products

The plan in force is the Stripe tier or a higher, unexpired admin grant (`effective_plan_key`), read from the platform
database by `MerchantRepository.effective_plan` when a create runs. Only creates are limited: reads, edits and deletes work
at the limit, and deleting a product frees a slot. A downgrade below the current count blocks new products but never
removes existing ones.

A new product has no row to lock, so `create` takes `pg_advisory_xact_lock` (`StoreCatalogueRepository.lock_catalogue`)
before counting; the lock is per database and each store has its own. Two concurrent creates therefore run one after
the other and only one can take the last slot. No schema change. The check is skipped for an unlimited plan.

Response: `409 {"error": "The Free plan allows 25 products per store. Upgrade your plan to add more."}`. The store limit answers the same way ("The Free plan allows 1 store. ..."); limits of 1 are singular ("1 team member").

## Staff

Invitations (KAN-62) are the only path that adds members besides the owner row written with the organisation. Both checks
run under the organisation row lock, so concurrent requests cannot take the same seat:

- **Create** (`POST /v1/organizations/{id}/invitations`) counts members **plus open invitations** and calls
  `require_staff_capacity(members + pending, organization.effective_plan)`. An open invitation holds a seat, so the plan
  cannot be oversold by invitations that would all fail on accept. Re-inviting an address replaces its open invitation, so
  it does not take a second seat.
- **Accept** (`POST /v1/invitations/accept`) counts members only, in the transaction that inserts the membership. A refused
  accept rolls back and leaves the invitation PENDING.

`StaffLimitReached` maps to 409 with `str(error)` ("The Free plan allows 1 team member. ..."). A downgrade below the current
count blocks new invitations and accepts but never removes members. See [backend team invitations](backend-team-invitations.md).

Tests: `tests/services/test_plan_limits.py`, `tests/api/test_products_plan_limit_e2e.py` (real Postgres, includes the concurrent case),
`tests/api/test_invitations_e2e.py` (staff limit on create and accept, concurrent creates and accepts).
