#!/usr/bin/env node
/**
 * Standalone logger verification script (pure JS, no TypeScript needed).
 * Tests Winston + DailyRotateFile exactly as configured in src/lib/logger.ts.
 *
 * Run with: node scripts/test-logger-verify.mjs
 */

import { createRequire } from 'module';
import { join } from 'path';
import { mkdirSync, existsSync, readFileSync } from 'fs';
import { fileURLToPath } from 'url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const projectRoot = join(__dirname, '..');
const require = createRequire(import.meta.url);

const LOG_DIR = join(projectRoot, 'logs');
const TODAY = new Date().toISOString().split('T')[0];
const APP_LOG = join(LOG_DIR, `app-${TODAY}.log`);
const ERROR_LOG = join(LOG_DIR, `error-${TODAY}.log`);

console.log('='.repeat(60));
console.log('Winston logger verification');
console.log('='.repeat(60));
console.log('Log dir   :', LOG_DIR);
console.log('App log   :', APP_LOG);
console.log('Error log :', ERROR_LOG);
console.log('');

// --- 1. Check dependencies ---
try {
  require('winston');
  console.log('[OK] winston installed');
} catch {
  console.error('[FAIL] winston not found — run: pnpm add winston');
  process.exit(1);
}
try {
  require('winston-daily-rotate-file');
  console.log('[OK] winston-daily-rotate-file installed');
} catch {
  console.error('[FAIL] winston-daily-rotate-file not found — run: pnpm add winston-daily-rotate-file');
  process.exit(1);
}

// --- 2. Create log dir ---
mkdirSync(LOG_DIR, { recursive: true });
console.log('[OK] logs/ directory ready');
console.log('');

// --- 3. Build logger (mirrors src/lib/logger.ts exactly) ---
const winston = require('winston');
require('winston-daily-rotate-file');

const fileFormat = winston.format.combine(
  winston.format.timestamp(),
  winston.format.errors({ stack: true }),
  winston.format.json()
);

const appTransport = new winston.transports.DailyRotateFile({
  dirname: LOG_DIR,
  filename: 'app-%DATE%.log',
  datePattern: 'YYYY-MM-DD',
  maxSize: '20m',
  maxFiles: '7d',
  format: fileFormat,
});

const errorTransport = new winston.transports.DailyRotateFile({
  dirname: LOG_DIR,
  filename: 'error-%DATE%.log',
  datePattern: 'YYYY-MM-DD',
  level: 'error',
  maxSize: '20m',
  maxFiles: '30d',
  format: fileFormat,
});

const instance = winston.createLogger({
  level: 'debug',
  defaultMeta: { service: 'saas-boilerplate' },
  transports: [
    appTransport,
    errorTransport,
    new winston.transports.Console({
      format: winston.format.combine(
        winston.format.colorize(),
        winston.format.timestamp({ format: 'HH:mm:ss' }),
        winston.format.printf(({ timestamp, level, message, service: _s, ...meta }) => {
          const metaStr = Object.keys(meta).length ? ` ${JSON.stringify(meta)}` : '';
          return `${timestamp} [${level}]: ${message}${metaStr}`;
        })
      ),
    }),
  ],
});

// --- 4. Write test entries ---
const testId = `verify-${Date.now()}`;
console.log(`Writing entries with testId=${testId} ...\n`);

instance.debug('Debug log entry',  { testId });
instance.info('Info log entry',    { testId });
instance.warn('Warning log entry', { testId });
instance.error('Error log entry',  { testId, err: 'test error' });

// --- 5. Flush: wait for both file transports to drain ---
// DailyRotateFile emits 'close' after the underlying file stream finishes.
// We wait on both transports before reading.
const waitForTransport = (transport) =>
  new Promise((resolve) => {
    // 'close' fires after the write stream is fully closed
    transport.once('close', resolve);
    // fallback: if 'close' never fires within 3s, continue anyway
    setTimeout(resolve, 3000);
  });

// Trigger close by ending the logger
instance.end();

console.log('\nWaiting for file streams to flush...');
await Promise.all([waitForTransport(appTransport), waitForTransport(errorTransport)]);

// Extra safety margin — some OS write buffers need a tick
await new Promise((r) => setTimeout(r, 200));

// --- 6. Verify ---
console.log('\nVerifying log files...\n');
let passed = true;

function checkFile(label, filePath, mustContain) {
  if (!existsSync(filePath)) {
    console.error(`[FAIL] ${label} not created: ${filePath}`);
    return false;
  }
  const content = readFileSync(filePath, 'utf8');
  const lines = content.trim().split('\n').filter((l) => l.includes(mustContain));
  if (lines.length === 0) {
    console.error(`[FAIL] ${label} exists (${content.length} bytes) but testId "${mustContain}" not found`);
    console.error('       Last 3 lines:', content.trim().split('\n').slice(-3).join(' | '));
    return false;
  }
  console.log(`[OK] ${label}: ${filePath}`);
  console.log(`     ${lines.length} matching entr${lines.length === 1 ? 'y' : 'ies'} written`);
  lines.forEach((l) => {
    try {
      const obj = JSON.parse(l);
      console.log(`     level=${obj.level}  message="${obj.message}"  ts=${obj.timestamp}`);
    } catch {
      console.log('    ', l);
    }
  });
  return true;
}

passed = checkFile('App log  ', APP_LOG, testId) && passed;
console.log('');
passed = checkFile('Error log', ERROR_LOG, testId) && passed;

console.log('');
if (passed) {
  console.log('ALL CHECKS PASSED — logger is writing to files correctly.');
  process.exit(0);
} else {
  console.error('SOME CHECKS FAILED — see above.');
  process.exit(1);
}
