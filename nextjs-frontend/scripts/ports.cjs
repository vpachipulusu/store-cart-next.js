/**
 * Ports and derived URLs for local dev and e2e (KAN-167), so two checkouts can run side by side.
 *
 *   PORT          next dev / next start                 (default 3000)
 *   E2E_PORT      the Playwright-managed server         (default 3000)
 *   BACKEND_PORT  the FastAPI dev server                (default 8000)
 *
 * Defaults are unchanged. CI and Vercel set none of these, so they are unaffected.
 */
const DEFAULT_FRONTEND_PORT = 3000;
const DEFAULT_BACKEND_PORT = 8000;
const MAX_PORT = 65535;

/** A TCP port from `value`, or `fallback` when it is unset or empty. Throws on anything else. */
function parsePort(value, fallback, name) {
  if (value === undefined || value === '') return fallback;
  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > MAX_PORT) {
    throw new Error(`${name} must be an integer between 1 and ${MAX_PORT}, got "${value}".`);
  }
  return port;
}

const getDevPort = (env = process.env) => parsePort(env.PORT, DEFAULT_FRONTEND_PORT, 'PORT');
const getE2ePort = (env = process.env) =>
  parsePort(env.E2E_PORT, DEFAULT_FRONTEND_PORT, 'E2E_PORT');
const getBackendPort = (env = process.env) =>
  parsePort(env.BACKEND_PORT, DEFAULT_BACKEND_PORT, 'BACKEND_PORT');

/** Origin of the e2e app server, for Playwright's baseURL and the e2e build's NEXT_PUBLIC_APP_URL. */
const getE2eBaseUrl = (env = process.env) => `http://localhost:${getE2ePort(env)}`;

/** Where the Next.js server reaches FastAPI unless BACKEND_API_URL is set explicitly. */
const getBackendApiUrl = (env = process.env) =>
  env.BACKEND_API_URL || `http://127.0.0.1:${getBackendPort(env)}`;

module.exports = {
  DEFAULT_FRONTEND_PORT,
  DEFAULT_BACKEND_PORT,
  parsePort,
  getDevPort,
  getE2ePort,
  getBackendPort,
  getE2eBaseUrl,
  getBackendApiUrl,
};
