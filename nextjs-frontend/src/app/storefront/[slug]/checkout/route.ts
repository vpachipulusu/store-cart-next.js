import { beginCheckout } from '@/lib/api/checkout';
import { failure, guardStoreRequest, jsonResponse } from '@/lib/storefront/cart-http';

/**
 * Starts checkout for the shopper's cart (KAN-77): `POST /storefront/{slug}/checkout`, reached on a store host as
 * `/checkout`. Answers `{ success, data: { checkoutUrl } }` for the basket to send the shopper to Stripe. The
 * order is only ever confirmed by the Connect webhook, never by anything the browser does after this.
 */

export const dynamic = 'force-dynamic';

const PASSED_STATUSES: ReadonlySet<number> = new Set([404, 409, 422, 429, 502, 503]);

export async function POST(
  request: Request,
  { params }: { params: Promise<{ slug: string }> }
): Promise<Response> {
  const { slug } = await params;
  const blocked = await guardStoreRequest(request, slug, { write: true });
  if (blocked) return blocked;
  const result = await beginCheckout(slug);
  if (result.success) return jsonResponse({ success: true, data: result.data }, 200);
  const { status } = result;
  if (status !== undefined && PASSED_STATUSES.has(status)) return failure(result.error, status);
  return failure(result.error, status === undefined ? 503 : 502);
}
