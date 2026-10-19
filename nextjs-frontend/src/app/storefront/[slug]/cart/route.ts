import { fetchCart } from '@/lib/api/cart';
import { cartResponse, guardStoreRequest } from '@/lib/storefront/cart-http';

/**
 * The shopper's cart (KAN-76), `GET /storefront/{slug}/cart`, reached on a store host as `/cart`. Priced from the
 * catalogue on every call; no cart yet reads as an empty cart. A route handler, like the storefront page, so the
 * status is decided after the backend answers.
 */

export const dynamic = 'force-dynamic';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ slug: string }> }
): Promise<Response> {
  const { slug } = await params;
  const blocked = await guardStoreRequest(request, slug, { write: false });
  if (blocked) return blocked;
  return cartResponse(await fetchCart(slug));
}
