import { addToCart } from '@/lib/api/cart';
import {
  addItemSchema,
  cartResponse,
  guardStoreRequest,
  parseBody,
} from '@/lib/storefront/cart-http';

/** Add a variant to the cart (KAN-76): `POST /storefront/{slug}/cart/items` with `{ variantId, quantity }`. */

export const dynamic = 'force-dynamic';

export async function POST(
  request: Request,
  { params }: { params: Promise<{ slug: string }> }
): Promise<Response> {
  const { slug } = await params;
  const blocked = await guardStoreRequest(request, slug, { write: true });
  if (blocked) return blocked;
  const body = await parseBody(request, addItemSchema);
  if (!body.ok) return body.response;
  return cartResponse(await addToCart(slug, body.value.variantId, body.value.quantity));
}
