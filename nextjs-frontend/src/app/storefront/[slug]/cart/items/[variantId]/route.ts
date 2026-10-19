import { removeFromCart, setCartQuantity } from '@/lib/api/cart';
import {
  cartResponse,
  failure,
  guardStoreRequest,
  parseBody,
  quantityBodySchema,
  variantIdSchema,
} from '@/lib/storefront/cart-http';

/**
 * One cart line (KAN-76): `PUT /storefront/{slug}/cart/items/{variantId}` with `{ quantity }` sets the quantity,
 * `DELETE` removes the line.
 */

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ slug: string; variantId: string }> };

export async function PUT(request: Request, { params }: Context): Promise<Response> {
  const { slug, variantId } = await params;
  const blocked = await guardStoreRequest(request, slug, { write: true });
  if (blocked) return blocked;
  if (!variantIdSchema.safeParse(variantId).success) return failure('Invalid request', 422);
  const body = await parseBody(request, quantityBodySchema);
  if (!body.ok) return body.response;
  return cartResponse(await setCartQuantity(slug, variantId, body.value.quantity));
}

export async function DELETE(request: Request, { params }: Context): Promise<Response> {
  const { slug, variantId } = await params;
  const blocked = await guardStoreRequest(request, slug, { write: true });
  if (blocked) return blocked;
  if (!variantIdSchema.safeParse(variantId).success) return failure('Invalid request', 422);
  return cartResponse(await removeFromCart(slug, variantId));
}
