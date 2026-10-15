# Dashboard store scope and switcher

**Last updated:** 2026-10-15 (KAN-61)

The dashboard layout (`src/app/dashboard/layout.tsx`) is scoped to one selected store and shows a switcher when the signed-in user can open several.

## How the selection works

- `fetchMerchantStores()` (`src/lib/api/stores.ts`, server-only) lists every store the user can open across all their organisations from `GET /v1/organizations`. When an organisation's embedded list is truncated (`stores_truncated`), it pages `GET /v1/organizations/{id}/stores`. Any failure fails the whole call; a partial list is never shown.
- The choice is kept in the httpOnly `selected-store` cookie, written by `selectStoreAction` (`src/app/actions/store-actions.ts`) only for a store id in the caller's own list.
- `getCurrentStoreSelection()` (`src/lib/stores/current.ts`, cached per request) re-validates the cookie against that list on every request and falls back to the first store. Zero stores gives an empty state, one store shows its name only, several show the switcher.

## The selection is a preference, not an authorization boundary

`data-store-id` on `<main>` and the cookie only decide what the dashboard shows. They do not grant access. Any page, server action or API call that scopes data by store must:

1. call `getCurrentStoreSelection()` on the server and use its `selected` store, never the cookie or a client-supplied id directly, and
2. rely on the backend to authorize the store id itself (store routes use `require_merchant`; organisation routes check membership).

## Tests

Unit: `store-selection`, `api/stores`, `actions/store-actions`, `components/store-switcher`, `app/dashboard-layout`. E2E: `src/__tests__/e2e/store-switcher.spec.ts` needs FastAPI (`BACKEND_API_URL`, `BACKEND_INTERNAL_KEY`) and skips otherwise.
