#!/usr/bin/env node
/**
 * Forwards Stripe TEST-mode webhooks to the backend's POST /webhooks/stripe (KAN-157).
 *
 *   node scripts/e2e-stripe-listen.mjs                forward until Ctrl+C (needs BACKEND_API_URL)
 *   node scripts/e2e-stripe-listen.mjs --print-secret print the signing secret `stripe listen` will use
 *
 * The backend must run with that signing secret (see docs/developer/local-e2e.md). Never paste the value anywhere.
 *
 * The Stripe CLI uses its own login (`stripe login`, test mode; `stripe listen` never uses live mode without --live).
 * The frontend holds no server secrets, so this script reads no env files and no key.
 */
import { spawn } from 'node:child_process';

const WEBHOOK_PATH = '/webhooks/stripe';
const args = ['listen'];
if (process.argv.includes('--print-secret')) {
  args.push('--print-secret');
} else {
  let target;
  try {
    target = new URL(process.env.BACKEND_API_URL ?? '');
  } catch {
    console.error(
      'BACKEND_API_URL is not set to a valid URL (the local uvicorn, e.g. http://127.0.0.1:8170).'
    );
    process.exit(1);
  }
  if (!['http:', 'https:'].includes(target.protocol) || target.search || target.hash) {
    console.error('BACKEND_API_URL must be a plain http(s) URL without a query or fragment.');
    process.exit(1);
  }
  target.pathname = `${target.pathname.replace(/\/+$/, '')}${WEBHOOK_PATH}`;
  args.push('--forward-to', target.toString());
}

const child = spawn('stripe', args, { stdio: 'inherit' });
child.on('error', (error) => {
  console.error(`Could not start the Stripe CLI (is it installed and on PATH?): ${error.message}`);
  process.exit(1);
});
child.on('exit', (code) => process.exit(code ?? 1));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
