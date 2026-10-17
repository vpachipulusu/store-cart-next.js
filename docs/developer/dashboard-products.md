# Merchant product screens (KAN-73)

Frontend for the product API ([backend-products-api.md](backend-products-api.md), KAN-245). The browser never calls FastAPI:
pages and server actions go through `src/lib/api/products.ts` (`callBackend` wrapper) and `src/app/actions/product-actions.ts`.

| Route | Does |
|---|---|
| `/dashboard/products` | Server-rendered list for the selected store: search (`q`: title or SKU), `status` and category filters go to the API; `limit` 25 and `offset` come from `?page=`. Nav entry "Products". |
| `/dashboard/products/new` | Create form: details, categories, up to 3 options, one variant row per option combination. Options cannot be edited after creation (API rule). |
| `/dashboard/products/[productId]` | Editor: details (title, slug, description, status, categories), per-variant edit/delete, add variant (products with options), image removal, delete product. |

Rules:

- The store always comes from `getCurrentStoreSelection()` on the server; the backend authorizes it again. Ids from the URL or the browser are shape-checked (`isEntityId`) before any call.
- Money is integer minor units in the store currency. Inputs take major units (`12.50`); `src/lib/products/money.ts` converts with string arithmetic and the currency exponent from `Intl` (JPY 0, KWD 3). The currency is the one the API reports (`ProductListResponse.currency`, `ProductData.currency`).
- Input is validated with one Zod schema set (`src/lib/products/schema.ts`) in the forms and again in the actions. Backend 404, 409 and 422 messages are curated by the API and shown; every other failure becomes a fixed message (`productErrorMessage`).
- `callBackend` only unwraps bodies with `success: true`; product responses are `{ data }`, so `callProduct` unwraps them.

## Search and categories (KAN-246)

- `q` is trimmed and cut to 100 characters (the API answers 422 above that); a blank one means no search. It matches the title or any variant SKU, ignoring case, and combines with the other filters.
- The category list (`GET /v1/stores/{store_id}/categories`, flat, at most 1000 rows) feeds the list filter and a checkbox tree in the create form and the editor (`src/lib/products/categories.ts`). When `truncated` is true the tree is not built: the list is shown flat, by name, and says it is partial. A linked id that is not in the list shows as "Unknown category (id)" and can be unticked.
- If the category list cannot be loaded, the filter keeps the chosen id as a hidden field and the editor falls back to adding and removing category ids.
- There is no category write route, so categories cannot be created here.

## Known gaps (API-shaped, not widened here)

- **Images.** No browser upload (storage CORS is undecided), so adding an image is not offered; existing images show by alt text and storage key (the public base URL is backend-only) and can be removed.
- **Options and add variant.** Options and values are fixed at creation; a product without options has exactly one variant, so "add variant" is only offered when the product has options.
- **Archive.** There is no archived status; "Draft" unpublishes.
- **Currency exponent.** Taken from the runtime `Intl` data; the API returns none.
- **Categories.** Created elsewhere; this story cannot create, rename or reorder them.
