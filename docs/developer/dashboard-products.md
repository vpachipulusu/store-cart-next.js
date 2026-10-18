# Merchant product screens (KAN-73)

Frontend for the product API ([backend-products-api.md](backend-products-api.md), KAN-245). The browser never calls FastAPI:
pages and server actions go through `src/lib/api/products.ts` (`callBackend` wrapper) and `src/app/actions/product-actions.ts`.

| Route | Does |
|---|---|
| `/dashboard/products` | Server-rendered list for the selected store: search (`q`: title or SKU), `status` and category filters go to the API; `limit` 25 and `offset` come from `?page=`. Nav entry "Products". |
| `/dashboard/products/new` | Create form: details, categories, up to 3 options, one variant row per option combination. Options cannot be edited after creation (API rule). |
| `/dashboard/products/[productId]` | Editor: details (title, slug, description, status, categories), per-variant edit/delete, add variant (products with options), add and remove images, delete product. |

Rules:

- The store always comes from `getCurrentStoreSelection()` on the server; the backend authorizes it again. Ids from the URL or the browser are shape-checked (`isEntityId`) before any call.
- Money is integer minor units in the store currency. Inputs take major units (`12.50`); `src/lib/products/money.ts` converts with string arithmetic and the currency exponent from `Intl` (JPY 0, KWD 3). The currency is the one the API reports (`ProductListResponse.currency`, `ProductData.currency`).
- Input is validated with one Zod schema set (`src/lib/products/schema.ts`) in the forms and again in the actions. Backend 404, 409 and 422 messages are curated by the API and shown; every other failure becomes a fixed message (`productErrorMessage`).
- Backend text is shown only when the API's own error envelope carried it (and only for 404, 409, 422, up to 200 characters). A raw FastAPI 422 with a `detail` list gets the fixed message.
- `callBackend` only unwraps bodies with `success: true`; product responses are `{ data }`, so `callProduct` unwraps them.

## Search and categories (KAN-246)

- `q` is trimmed and cut to 100 characters (the API answers 422 above that); a blank one means no search. It matches the title or any variant SKU, ignoring case, and combines with the other filters.
- The category list (`GET /v1/stores/{store_id}/categories`, flat, at most 1000 rows) feeds the list filter and a checkbox tree in the create form and the editor (`src/lib/products/categories.ts`). When `truncated` is true the tree is not built: the list is shown flat, by name, and says it is partial. A linked id that is not in the list shows as "Unknown category (id)" and can be unticked.
- If the category list cannot be loaded, the filter keeps the chosen id as a hidden field and the editor falls back to adding and removing category ids.
- There is no category write route, so categories cannot be created here.

## Adding images (KAN-249)

The editor's Images panel has an "Add image" form. The file goes from the browser straight to Cloudflare R2; it never passes through Next.js or FastAPI.

1. The form checks type (JPEG, PNG, WebP; no SVG) and size (1 byte to 10 MB) before any request (`src/lib/products/image-upload.ts`, shared with the actions).
2. `presignImageUploadAction` re-validates, then calls `POST /v1/stores/{store_id}/uploads/images` (KAN-66) through `presignProductImage`. It refuses a ticket whose key is outside `stores/{selected store}/` or whose URL is not https (http only for localhost). The presigned URL is a credential: it is returned to the browser once and never logged.
3. The browser PUTs the file to the presigned URL with the signed `Content-Type` (`src/lib/products/upload-client.ts`, XMLHttpRequest for upload progress). The signature also covers the exact size.
4. `addImageAction` registers the key with `POST .../products/{product_id}/images`, checking the store prefix again (the backend checks it too).

Errors are shown in `role="alert"` regions: wrong type, too large, empty file, storage unreachable (network or a CORS policy that blocks the site; script cannot tell them apart, so the message names both), storage rejected the PUT (expired link or mismatch), and backend messages for presign and registration.

**Orphaned objects.** If the PUT succeeds but registration fails, the form keeps the uploaded key and offers Retry, which registers it again without uploading twice. There is no route to delete an object, so a file the merchant abandons stays in the bucket unreferenced. Clean-up of unreferenced `stores/` objects belongs to a bucket lifecycle rule or a backend job (not part of this story).

**Owner step (bucket CORS checklist).** Names only, no secrets. Compare the bucket's CORS policy (Cloudflare dashboard, R2, the bucket, Settings, CORS policy; see https://developers.cloudflare.com/r2/buckets/cors/) with what the browser sends:

- The request is a cross-origin `PUT` straight to the presigned `https://<account>.r2.cloudflarestorage.com/<bucket>/stores/<store id>/<id>.<jpg|png|webp>?X-Amz-...` URL, with `XMLHttpRequest`, no cookies and no credentials.
- The request headers come from the backend's presign ticket (`headers`, today only `Content-Type`: `image/jpeg`, `image/png` or `image/webp`, exactly as signed). The code applies them verbatim; the browser ignores forbidden ones (for example `Content-Length`) and adds `Origin` itself. So the preflight (`OPTIONS`) asks for `Access-Control-Request-Method: PUT` and `Access-Control-Request-Headers: content-type`. If the backend ever adds a signed header, it must be added to AllowedHeaders too.
- **AllowedOrigins:** each exact app origin that uploads (scheme and host, no path, no trailing slash): the production dashboard origin, plus any preview or local origin you want to allow. R2 CORS has no wildcard subdomains (`https://*.example.com` does not work), so every origin is listed exactly. `*` also works for a bucket with no credentialed use but is not needed.
- **AllowedMethods:** `PUT` (required). `GET` and `HEAD` are fine for later reads.
- **AllowedHeaders:** `Content-Type` (required). Any extra header the code adds later must be listed too.
- **ExposeHeaders** (optional): `ETag`. The code does not read it. **MaxAgeSeconds** (optional): for example `3600`, to cache the preflight.
- An expired or mismatched presigned URL answers `403` without CORS headers, which the browser reports as a plain network error. The form therefore asks for a fresh URL right before every upload (the link lives 300 seconds) and shows one message that names both causes (network and CORS). A registration retry never reuses a link.
- Status of this checklist: the code side is verified by unit tests and a local e2e with a stubbed storage host. The real bucket policy is **not verified from code**: the bucket host is a backend setting that was deliberately not read, so no preflight was sent to it. The owner confirms it by uploading one image from the production dashboard.

The backend needs its R2 settings (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `R2_PUBLIC_BASE_URL`); without them presigning answers 503 and the form shows "Products could not be reached".

**Local e2e.** `product-management.spec.ts` always checks that the form is present. The upload steps (validation, storage failure, successful upload and persistence) run only with `E2E_IMAGE_UPLOAD=1`. They need a throwaway backend started with made-up R2 test values (the signer works offline), and they stand in for storage with a Playwright route on `*.r2.cloudflarestorage.com`; no real bucket is touched.

## Known gaps (API-shaped, not widened here)

- **Images.** Add and remove work; there is no reorder or alt-text edit (re-add instead), no delete of the stored object on removal or after a failed registration, and existing images show by alt text and storage key because the public base URL is backend-only (no thumbnails).
- **Options and add variant.** Options and values are fixed at creation; a product without options has exactly one variant, so "add variant" is only offered when the product has options.
- **Description.** Plain text: it is stored and shown as typed, never as HTML or Markdown.
- **Archive.** There is no archived status; "Draft" unpublishes.
- **Currency exponent.** Taken from the runtime `Intl` data; the API returns none.
- **Categories.** Created elsewhere; this story cannot create, rename or reorder them.
