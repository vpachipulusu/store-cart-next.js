# Plan limits on create (KAN-84)

The numbers live in `fastapi_backend/app/core/plans.py` (`PLANS`; `None` is unlimited). Every limit is enforced where the
resource is created, in the same transaction as the insert, and refused with **409** and a message that names the plan and
says to upgrade. Messages are built in `app/services/plan_limits.py` and hold no store data.

| Limit | Scope | Enforced in | Status |
|---|---|---|---|
| `max_stores` | organisation (archived stores do not count) | `OrganizationsService.create_store`, under the organisation row lock (KAN-45) | done |
| `max_products` | **per store**, drafts included | `StoreProductsService.create` (`POST /v1/stores/{store_id}/products`) | done (KAN-84) |
| `max_staff` | organisation, every membership counts (owner included) | `require_staff_capacity` in `plan_limits.py` | helper only, see below |

## Products

The plan in force is the Stripe tier or a higher, unexpired admin grant (`effective_plan_key`), read from the platform
database by `MerchantRepository.effective_plan` when a create runs. Only creates are limited: reads, edits and deletes work
at the limit, and deleting a product frees a slot. A downgrade below the current count blocks new products but never
removes existing ones.

A new product has no row to lock, so `create` takes `pg_advisory_xact_lock` (`StoreCatalogueRepository.lock_catalogue`)
before counting; the lock is per database and each store has its own. Two concurrent creates therefore run one after
the other and only one can take the last slot. No schema change. The check is skipped for an unlimited plan.

Response: `409 {"error": "The Free plan allows 25 products per store. Upgrade your plan to add more."}`.

## Staff

No path adds members besides the owner row written with the organisation (a count of 0 against a minimum limit of 1), so
nothing is enforced yet. The invitation flow (KAN-62) must, in the transaction that inserts the membership and under the
organisation row lock (as `create_store` does), count memberships and call
`require_staff_capacity(count, organization.effective_plan)`, then map `StaffLimitReached` to 409 with `str(error)`. The helper and its
tests exist; the create path carries over to KAN-62.

Tests: `tests/services/test_plan_limits.py`, `tests/api/test_products_plan_limit_e2e.py` (real Postgres, includes the concurrent case).
