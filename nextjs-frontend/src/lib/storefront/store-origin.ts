import 'server-only';

import { resolvePlatformRootDomain } from './host';
import { storeOrigin } from './seo';

/** The public origin of a store's host, from PLATFORM_ROOT_DOMAIN (and PORT for `*.localhost`). */
export function originFor(slug: string): string {
  return storeOrigin(
    slug,
    resolvePlatformRootDomain(process.env.PLATFORM_ROOT_DOMAIN),
    process.env.PORT
  );
}
