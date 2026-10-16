# Image uploads (KAN-66)

`POST /v1/stores/{store_id}/uploads/images` returns a presigned URL for one image under `stores/{store_id}/` in the
Cloudflare R2 bucket. The file never passes through the API.

- **Who:** OWNER or ADMIN of an ACTIVE store (`require_merchant(OWNER_ADMIN)`). STAFF get 403, another tenant's store
  is 404, a non-active store is rejected. Unset R2 settings answer 503.
- **Body:** `{"content_type": "image/jpeg" | "image/png" | "image/webp", "size_bytes": 1..10485760}`. SVG is never
  allowed.
- **Response:** `data.upload_url`, `method` (`PUT`), `headers` (send them exactly), `key`, `public_url`, `expires_at`.
  The URL is valid for 300 seconds.
- **Signature:** R2 has no presigned POST policies, so the client does a `PUT` and the signature covers
  `Content-Type` and `Content-Length`. A different type or size fails at R2. The key is built on the server
  (`stores/{store_id}/{id}.{ext}`); no client filename reaches it.
- **Logging:** the presigned URL's query string is a credential. It is never logged.

## Settings

`R2_ACCOUNT_ID` (32 hex characters), `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`,
`R2_PUBLIC_BASE_URL` (https, no query or fragment). All five or none.

## Owner step: bucket CORS

In the Cloudflare dashboard, set the bucket CORS policy to allow `PUT` from the app origins with the `Content-Type`
header, otherwise browser uploads fail. The app's CSP `connect-src` must also allow the R2 host (separate story).
