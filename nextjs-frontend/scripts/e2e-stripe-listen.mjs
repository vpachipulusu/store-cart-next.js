#!/usr/bin/env node
/**
 * Forwards Stripe TEST-mode webhooks to the backend's POST /webhooks/stripe (KAN-157).
 *
 *   node scripts/e2e-stripe-listen.mjs                forward until Ctrl+C (needs BACKEND_API_URL)
 *   node scripts/e2e-stripe-listen.mjs --print-secret print the signing secret `stripe listen` will use
 *
 * The backend verifies each event with STRIPE_WEBHOOK_SECRET, which must equal the secret printed by
 * `--print-secret` (it is stable for one Stripe account and CLI login). Never paste the value anywhere.
 *
 * Reads STRIPE_SECRET_KEY (a test-mode key) from the environment or .env.e2e.local and hands it to the Stripe
 * CLI through STRIPE_API_KEY, so it never appears on a command line. Without a key the CLI's own login is used.
 */
import { spawn } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const WEBHOOK_PATH = '/webhooks/stripe';

function readEnvFile(name) {
  const file = resolve(root, name);
  if (!existsSync(file)) return {};
  const values = {};
  for (const line of readFileSync(file, 'utf8').split(/\r?\n/)) {
    const match = /^\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*?)\s*$/.exec(line);
    if (match) values[match[1]] = match[2].replace(/^(['"])(.*)\1$/, '$2');
  }
  return values;
}

const fileEnv = readEnvFile('.env.e2e.local');
const pick = (name) => process.env[name] || fileEnv[name] || '';

const apiKey = pick('STRIPE_SECRET_KEY');
if (apiKey && !/^(sk|rk)_test_/.test(apiKey)) {
  console.error(
    'STRIPE_SECRET_KEY must be a test-mode key (sk_test_ or rk_test_). Refusing to listen.'
  );
  process.exit(1);
}

const childEnv = { ...process.env };
if (apiKey) childEnv.STRIPE_API_KEY = apiKey;

const printSecret = process.argv.includes('--print-secret');
const args = ['listen'];
if (printSecret) {
  args.push('--print-secret');
} else {
  const backend = pick('BACKEND_API_URL');
  if (!backend) {
    console.error(
      'BACKEND_API_URL is not set (the local uvicorn URL, e.g. http://127.0.0.1:8170).'
    );
    process.exit(1);
  }
  let target;
  try {
    target = new URL(backend);
  } catch {
    console.error('BACKEND_API_URL is not a valid URL.');
    process.exit(1);
  }
  if (!['http:', 'https:'].includes(target.protocol) || target.search || target.hash) {
    console.error('BACKEND_API_URL must be a plain http(s) URL without a query or fragment.');
    process.exit(1);
  }
  target.pathname = `${target.pathname.replace(/\/+$/, '')}${WEBHOOK_PATH}`;
  args.push('--forward-to', target.toString());
}

const child = spawn('stripe', args, {
  env: childEnv,
  stdio: 'inherit',
  shell: process.platform === 'win32',
});
child.on('error', (error) => {
  console.error(`Could not start the Stripe CLI (is it installed and on PATH?): ${error.message}`);
  process.exit(1);
});
child.on('exit', (code) => process.exit(code ?? 1));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
