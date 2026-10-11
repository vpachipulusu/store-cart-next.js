# StoreCart backlog → Jira

Jira project: **Store Cart** (key `KAN`) — https://storecart.atlassian.net/browse/KAN

Source of truth for the text: [backlog.json](backlog.json). Issue keys below were created on 2026-10-11.

| Epic | Jira | Stories (backlog ref → key) |
|---|---|---|
| E1 Monorepo restructure | KAN-4 | E1.1–E1.5 → KAN-25 … KAN-29; E1.6 → KAN-111; E1.7 → KAN-113 |
| E2 Backend foundation (FastAPI template) | KAN-5 | E2.1–E2.6 → KAN-30 … KAN-35; E2.7 → KAN-112 |
| E3 Platform data and authentication | KAN-6 | E3.1–E3.6 → KAN-36 … KAN-41 |
| E4 Organisation billing (Stripe Billing) | KAN-7 | E4.1–E4.4 → KAN-42 … KAN-45 |
| E5 Platform admin | KAN-8 | E5.1–E5.5 → KAN-46 … KAN-50 |
| E6 Frontend decoupling | KAN-9 | E6.1 → KAN-51 |
| E7 Multi-tenancy core (one database per store) | KAN-10 | E7.1–E7.7 → KAN-52 … KAN-58 |
| E8 Merchant onboarding and team | KAN-11 | E8.1–E8.5 → KAN-59 … KAN-63 |
| E9 Storefront routing and media | KAN-12 | E9.1–E9.3 → KAN-64 … KAN-66 |
| E10 Stripe Connect payments | KAN-13 | E10.1–E10.3 → KAN-67 … KAN-69 |
| E11 Catalogue and inventory | KAN-14 | E11.1–E11.5 → KAN-70 … KAN-74 |
| E12 Storefront and cart | KAN-15 | E12.1–E12.3 → KAN-75 … KAN-77 |
| E13 Orders, fulfilment and refunds | KAN-16 | E13.1–E13.4 → KAN-78 … KAN-81 |
| E14 Store settings: shipping, tax and plan limits | KAN-17 | E14.1–E14.3 → KAN-82 … KAN-84 |
| E15 Custom domains | KAN-18 | E15.1–E15.2 → KAN-85 … KAN-86 |
| E16 Discounts and coupons | KAN-19 | E16.1–E16.2 → KAN-87 … KAN-88 |
| E17 Shipping zones and Stripe Tax | KAN-20 | E17.1–E17.3 → KAN-89 … KAN-91 |
| E18 Shopper accounts | KAN-21 | E18.1–E18.2 → KAN-92 … KAN-93 |
| E19 Returns, abandoned carts and analytics | KAN-22 | E19.1–E19.3 → KAN-94 … KAN-96 |
| E20 VevoCart parity features | KAN-23 | E20.1–E20.11 → KAN-97 … KAN-107 |
| E21 Marketplace mode and merchant mobile app | KAN-24 | E21.1–E21.3 → KAN-108 … KAN-110 |

Story keys are sequential within each range in backlog order (e.g. E1.3 = KAN-27). E1.6 and E2.7 were added later (template adoption) and have out-of-range keys.

Plan: [../storecart-plan.md](../storecart-plan.md).

Commit and branch convention: include the Jira key, e.g. `feat(KAN-25): move Next.js app into frontend/`.
