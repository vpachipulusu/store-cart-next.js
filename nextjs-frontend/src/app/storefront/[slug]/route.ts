import { headers } from 'next/headers';
import { fetchStorefront } from '@/lib/api/storefront';
import { STORE_SLUG_HEADER } from '@/lib/storefront/host';
import { renderDocument } from '@/lib/storefront/html';

/**
 * Public storefront (KAN-64). Reached only through the proxy rewrite from `{slug}.<platform root domain>`.
 *
 * A route handler and not a page on purpose: the app's root `loading.tsx` makes pages stream, which sends the
 * HTTP status before the lookup finishes, so a missing store would answer 200 with a not-found body. Here the
 * status is decided after the lookup. It renders only the public fields (name) and nothing else. Unknown,
 * suspended and any other non-live store, and any request that did not come through the proxy rewrite for this
 * same slug, get the same 404.
 */

export const dynamic = 'force-dynamic';

const HTML_HEADERS = {
  'Content-Type': 'text/html; charset=utf-8',
  'Cache-Control': 'no-store',
} as const;

function notFoundResponse(): Response {
  return new Response(
    renderDocument('Store not found', 'Store not found', 'This store does not exist.', 'noindex'),
    {
      status: 404,
      headers: HTML_HEADERS,
    }
  );
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ slug: string }> }
): Promise<Response> {
  const { slug } = await params;
  // The proxy sets this header from the Host it rewrote; a direct `/storefront/<slug>` hit has none.
  if ((await headers()).get(STORE_SLUG_HEADER) !== slug) return notFoundResponse();

  let store;
  try {
    store = await fetchStorefront(slug);
  } catch {
    // An outage is not "store does not exist": answer 503 so it is never cached or indexed as a missing store.
    return new Response(
      renderDocument(
        'Unavailable',
        'Temporarily unavailable',
        'Please try again shortly.',
        'noindex'
      ),
      { status: 503, headers: { ...HTML_HEADERS, 'Retry-After': '30' } }
    );
  }
  if (!store) return notFoundResponse();

  return new Response(
    renderDocument(
      store.name,
      store.name,
      'Welcome to our store. Products are coming soon.',
      'index'
    ),
    { status: 200, headers: HTML_HEADERS }
  );
}
