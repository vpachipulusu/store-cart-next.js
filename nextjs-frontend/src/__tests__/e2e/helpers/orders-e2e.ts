import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { BACKEND_DIR } from './products-e2e';

/**
 * Seeding helper for orders-management.spec.ts (KAN-79). There is no checkout yet, so orders are written by the
 * backend's own order service through seed_orders.py (uv, in E2E_BACKEND_DIR, the fastapi_backend folder).
 */

const SEED_SCRIPT = path.join(path.dirname(fileURLToPath(import.meta.url)), 'seed_orders.py');

/** Adds an active product, a PAID order and a PENDING order to the store; returns the paid order id. */
export function seedOrders(storeId: string): string {
  if (!BACKEND_DIR) throw new Error('Seeding needs E2E_BACKEND_DIR');
  const output = execFileSync('uv', ['run', 'python', SEED_SCRIPT, storeId], {
    cwd: BACKEND_DIR,
    // Same inheritance as the store activation helper: the script needs the backend settings of uvicorn.
    env: { ...process.env, PYTHONPATH: BACKEND_DIR },
    stdio: 'pipe',
    timeout: 120_000,
  });
  return output.toString().trim();
}
