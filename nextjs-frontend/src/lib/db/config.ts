/**
 * Whether a database connection string is configured.
 *
 * Kept separate from `@/lib/db/client` so callers can check it without importing Prisma. Used by reads that
 * run while `next build` prerenders static routes (root layout settings), where CI and secret-less image
 * builds have no DATABASE_URL and must fall back to defaults instead of issuing a query that cannot succeed.
 */
export function isDatabaseConfigured(): boolean {
  return Boolean(process.env.DATABASE_URL?.trim());
}
