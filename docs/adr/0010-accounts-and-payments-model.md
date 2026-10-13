# ADR-010: Account structure, seller of record and platform revenue

- **Status:** Accepted by the product owner, 2026-10-12
- **Date:** 2026-10-11
- **Plan decisions:** D3 (account structure), D4 (seller of record), D9 (platform revenue)
- **Jira:** KAN-29; carried out in E3/E4 (KAN-36 …, KAN-42 …) and E10 (KAN-67 …)

## Context

The boilerplate is single-user: subscription state sits on the `User` row. StoreCart merchants are businesses
with staff and several stores, and they sell to their own customers. These product choices decide the platform
data model and the payment and legal setup, so they are recorded with the architecture.

## Decision

- **Account structure (D3):** Organisation → Membership (`OWNER`, `ADMIN`, `STAFF`) → several Stores. Users
  belong to organisations through memberships, and authorisation checks the membership role
  ([ADR-003](0003-nextjs-to-fastapi-authentication.md)).
- **Seller of record (D4):** each merchant sells through **Stripe Connect direct charges** on their own
  connected account. The merchant, not StoreCart, is the seller of record and handles refunds, disputes and tax
  liability.
- **Platform revenue (D9):** subscription only, billed with **Stripe Billing on the organisation** (not the
  user). A `platform_fee_bps` field is kept at `0`, reserved for a possible per-order fee later.

## Alternatives considered

- **Billing per user (the boilerplate).** Fails as soon as a business has more than one staff member.
- **Destination charges or separate charges and transfers.** StoreCart would become the seller of record,
  taking on refund, dispute and tax liability.
- **A percentage fee per order from day one.** Discourages early merchants; the reserved field keeps the
  option open.

## Consequences

- Subscription fields move from `User` to `Organisation` (E3/E4).
- Two separate Stripe integrations with separate webhook endpoints and secrets: Billing for the platform,
  Connect for stores.
- Any later per-order fee is a data change (`platform_fee_bps`) plus a Connect application fee, not a new
  architecture.
