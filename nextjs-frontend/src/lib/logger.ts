import * as Sentry from '@sentry/nextjs';
import { siteConfig } from '@/config/site';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type LogMeta = Record<string, unknown> | unknown;

interface Logger {
  error(message: string, meta?: LogMeta): void;
  warn(message: string, meta?: LogMeta): void;
  info(message: string, meta?: LogMeta): void;
  debug(message: string, meta?: LogMeta): void;
}

// ---------------------------------------------------------------------------
// Redaction (KAN-171)
//
// Pure functions, no Winston/Sentry dependency. Everything that leaves the
// logger (Winston console + file transports, console fallback, Sentry) goes
// through them, so PII and secrets in error objects, messages and metadata
// never reach a log sink.
// ---------------------------------------------------------------------------

const REDACTED = '[REDACTED]';
const UNREDACTABLE = '[unredactable]';
const MAX_DEPTH = 8;
const MAX_ERROR_MESSAGE_LENGTH = 500;
// Bounds regex work on hostile or oversized input (ReDoS guard).
const MAX_REDACT_INPUT_LENGTH = 10_000;

// Order matters: block/structured secrets first, generic shapes last.
const SENSITIVE_STRING_PATTERNS: readonly RegExp[] = [
  /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)/g,
  /\bBearer\s+[A-Za-z0-9._~+/=-]+/gi,
  /\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*/g, // JWT (ID token, session cookie)
  /(?<![A-Za-z0-9])(?:sk|rk|pk|ek)_(?:live|test)_[A-Za-z0-9]+/g, // Stripe API keys
  /\bwhsec_[A-Za-z0-9]+/g, // Stripe webhook secret
  /\bAIza[0-9A-Za-z_-]{35}\b/g, // Google API key
  /(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,255}\.[A-Za-z]{2,}/g, // email (bounded)
  // Firebase uid: 28 alphanumerics, mixed case
  /\b(?=[A-Za-z0-9]{28}\b)(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*[A-Z])[A-Za-z0-9]{28}\b/g,
  /[A-Za-z0-9+/=_-]{40,}/g, // any other long opaque token (incl. base64)
];

const SENSITIVE_KEY_FRAGMENTS: readonly string[] = [
  'password',
  'passwd',
  'token',
  'secret',
  'apikey',
  'privatekey',
  'authorization',
  'cookie',
  'credential',
  'signature',
  'email',
  'phone',
  'displayname',
  'address',
  'oobcode',
  'localid',
  'customerdetails',
  'billingdetails',
];

function isSensitiveKey(key: string): boolean {
  const normalized = key.toLowerCase().replace(/[^a-z0-9]/g, '');
  return (
    normalized === 'sub' ||
    normalized.endsWith('uid') ||
    SENSITIVE_KEY_FRAGMENTS.some((f) => normalized.includes(f))
  );
}

export function redactString(input: string): string {
  let raw: string;
  try {
    raw = String(input);
  } catch {
    return UNREDACTABLE;
  }
  const bounded =
    raw.length > MAX_REDACT_INPUT_LENGTH
      ? `${raw.slice(0, MAX_REDACT_INPUT_LENGTH)} [TRUNCATED]`
      : raw;
  return SENSITIVE_STRING_PATTERNS.reduce(
    (text, pattern) => text.replace(pattern, REDACTED),
    bounded
  );
}

function isErrorLike(value: unknown): value is Error {
  return value instanceof Error || Object.prototype.toString.call(value) === '[object Error]';
}

/** Reduce any error (Firebase, Prisma, Stripe, ...) to name, code and a redacted message. */
function redactError(error: Error): Record<string, string> {
  const code = (error as { code?: unknown }).code;
  return {
    name: redactString(String(error.name)),
    ...(typeof code === 'string' || typeof code === 'number'
      ? { code: redactString(String(code)) }
      : {}),
    message: redactString(String(error.message).slice(0, MAX_REDACT_INPUT_LENGTH)).slice(
      0,
      MAX_ERROR_MESSAGE_LENGTH
    ),
  };
}

function redactValue(
  value: unknown,
  key: string | undefined,
  depth: number,
  ancestors: WeakSet<object>
): unknown {
  if (value === null || value === undefined) return value;

  if (key !== undefined && isSensitiveKey(key)) {
    // Flags and counts (e.g. emailVerified) carry no secret.
    return typeof value === 'boolean' || typeof value === 'number' ? value : REDACTED;
  }

  switch (typeof value) {
    case 'string':
      return redactString(value);
    case 'number':
    case 'boolean':
      return value;
    case 'bigint':
      return value.toString();
    case 'function':
    case 'symbol':
      return `[${typeof value}]`;
  }

  const obj = value as object;
  if (isErrorLike(obj)) return redactError(obj);
  if (obj instanceof Date) return obj.toISOString();
  if (ArrayBuffer.isView(obj) || obj instanceof ArrayBuffer) return '[Binary]';
  if (ancestors.has(obj)) return '[Circular]';
  if (depth >= MAX_DEPTH) return '[MaxDepth]';

  ancestors.add(obj);
  try {
    if (Array.isArray(obj)) {
      return obj.map((item) => redactValue(item, undefined, depth + 1, ancestors));
    }
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(obj)) {
      if (k === '__proto__') continue;
      const safeKey = redactString(k);
      try {
        out[safeKey] = redactValue((obj as Record<string, unknown>)[k], k, depth + 1, ancestors);
      } catch {
        out[safeKey] = '[Unreadable]';
      }
    }
    return out;
  } finally {
    ancestors.delete(obj);
  }
}

/** Returns a redacted deep copy; never mutates the input. Never throws. */
export function redactLogData(value: unknown): unknown {
  try {
    return redactValue(value, undefined, 0, new WeakSet());
  } catch {
    return UNREDACTABLE;
  }
}

/** Winston `info` entries are redacted in place (symbol keys such as LEVEL/SPLAT must survive). */
export function redactLogEntry<T extends Record<string, unknown>>(info: T): T {
  const entry = info as Record<string, unknown>;
  for (const key of Object.keys(entry)) {
    if (key === 'level') continue;
    try {
      entry[key] = redactValue(entry[key], key, 0, new WeakSet());
    } catch {
      entry[key] = UNREDACTABLE;
    }
  }
  return info;
}

/** Winston format layer applied at logger level, so every transport (console, files) is covered. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- winston is loaded via require() and untyped here
export function buildRedactionFormat(winston: any): any {
  return winston.format((info: Record<string, unknown>) => redactLogEntry(info))();
}

// ---------------------------------------------------------------------------
// Environment detection
// ---------------------------------------------------------------------------

const isServer = typeof window === 'undefined';

// ---------------------------------------------------------------------------
// Winston (server-only) — loaded via require() so webpack eliminates this
// code path from client bundles. `serverExternalPackages` in next.config.ts
// keeps Winston out of the server bundle too (loaded at runtime).
// ---------------------------------------------------------------------------

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type WinstonLogger = any;

const globalForWinston = globalThis as unknown as {
  __winstonLogger?: WinstonLogger;
  __exitHandlerRegistered?: boolean;
};

function getWinstonLogger(): WinstonLogger | null {
  if (!isServer) return null;

  if (globalForWinston.__winstonLogger) {
    return globalForWinston.__winstonLogger;
  }

  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const winston = require('winston');
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    require('winston-daily-rotate-file');
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const path = require('path');
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const fs = require('fs');

    const LOG_DIR = path.join(process.cwd(), 'logs');
    fs.mkdirSync(LOG_DIR, { recursive: true });

    const LOG_LEVEL =
      process.env.LOG_LEVEL || (process.env.NODE_ENV === 'production' ? 'info' : 'debug');

    // Shared file format for both environments
    const fileFormat = winston.format.combine(
      winston.format.timestamp(),
      winston.format.errors({ stack: true }),
      winston.format.json()
    );

    // File transports run in all environments — Winston streams are async (non-blocking)
    const instance = winston.createLogger({
      level: LOG_LEVEL,
      // First in the chain: runs before any transport format (KAN-171).
      format: buildRedactionFormat(winston),
      defaultMeta: {
        service: siteConfig.name
          .trim()
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-'),
      },
      transports: [
        new winston.transports.DailyRotateFile({
          dirname: LOG_DIR,
          filename: 'app-%DATE%.log',
          datePattern: 'YYYY-MM-DD',
          maxSize: '20m',
          maxFiles: process.env.NODE_ENV === 'production' ? '14d' : '7d',
          format: fileFormat,
        }),
        new winston.transports.DailyRotateFile({
          dirname: LOG_DIR,
          filename: 'error-%DATE%.log',
          datePattern: 'YYYY-MM-DD',
          level: 'error',
          maxSize: '20m',
          maxFiles: '30d',
          format: fileFormat,
        }),
      ],
    });

    // Console transport
    if (process.env.NODE_ENV !== 'production') {
      instance.add(
        new winston.transports.Console({
          format: winston.format.combine(
            winston.format.colorize(),
            winston.format.timestamp({ format: 'HH:mm:ss' }),
            winston.format.printf(
              ({ timestamp, level, message, service: _s, ...meta }: Record<string, unknown>) => {
                const metaStr = Object.keys(meta).length ? ` ${JSON.stringify(meta)}` : '';
                return `${timestamp} [${level}]: ${message}${metaStr}`;
              }
            )
          ),
        })
      );
    } else {
      instance.add(
        new winston.transports.Console({
          format: winston.format.combine(
            winston.format.timestamp(),
            winston.format.errors({ stack: true }),
            winston.format.json()
          ),
        })
      );
    }

    // Flush file stream buffers on process exit.
    // Winston file transports buffer writes in Node.js streams. On HMR reloads
    // or graceful shutdown, calling instance.close() signals all transports to
    // flush and close their streams without forcing a process.exit().
    if (!globalForWinston.__exitHandlerRegistered) {
      globalForWinston.__exitHandlerRegistered = true;

      const flush = () => instance.close();

      process.once('SIGTERM', flush);
      process.once('SIGINT', flush);
      process.once('beforeExit', flush);
      process.once('uncaughtException', (error) => {
        instance.error('Uncaught exception', { error: error.message, stack: error.stack });
        instance.close();
      });
      process.once('unhandledRejection', (reason) => {
        instance.error('Unhandled rejection', { reason });
        instance.close();
      });
    }

    // Singleton — prevent HMR duplication
    globalForWinston.__winstonLogger = instance;

    instance.info('Logger initialized', {
      level: LOG_LEVEL,
      environment: process.env.NODE_ENV,
      logDir: LOG_DIR,
    });

    return instance;
  } catch (err) {
    console.error('[logger] Winston failed to initialize, falling back to console:', err);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Sentry helpers — fire-and-forget via setImmediate so they never block the
// request/response cycle. Sentry's SDK batches internally; we just avoid the
// synchronous serialization cost on the hot path.
// ---------------------------------------------------------------------------

function normalizeMeta(meta: LogMeta | undefined): Record<string, unknown> | undefined {
  if (meta === undefined || meta === null) return undefined;
  if (typeof meta === 'object' && !Array.isArray(meta)) return meta as Record<string, unknown>;
  return { value: meta };
}

/** Rebuild an Error for Sentry that keeps its stack but carries only redacted text. */
function redactedErrorForSentry(error: Error, message: string): Error {
  const safe = new Error(redactString(error.message || message));
  safe.name = redactString(error.name);
  safe.stack = error.stack ? redactString(error.stack) : undefined;
  const code = (error as { code?: unknown }).code;
  if (typeof code === 'string' || typeof code === 'number') {
    (safe as Error & { code?: string }).code = redactString(String(code));
  }
  return safe;
}

function sentryCaptureError(message: string, meta: LogMeta | undefined): void {
  setImmediate(() => {
    try {
      const original = normalizeMeta(meta);
      const found = isErrorLike(meta)
        ? meta
        : isErrorLike(original?.error)
          ? (original?.error as Error)
          : undefined;
      const error = found ? redactedErrorForSentry(found, message) : new Error(message);
      Sentry.captureException(error, {
        extra: normalizeMeta(redactLogData(meta)),
      });
    } catch {
      // Sentry not initialized or DSN not set — silently skip
    }
  });
}

function sentryBreadcrumb(
  level: 'warning' | 'info' | 'debug',
  message: string,
  safeMeta: LogMeta | undefined
): void {
  setImmediate(() => {
    try {
      Sentry.addBreadcrumb({
        level,
        message,
        data: normalizeMeta(safeMeta) as Record<string, unknown> | undefined,
      });
    } catch {
      // Sentry not initialized — silently skip
    }
  });
}

// ---------------------------------------------------------------------------
// Unified logger
//
// Server: Winston (file + console) + Sentry (errors/breadcrumbs, deferred)
// Client: console + Sentry (errors/breadcrumbs, deferred)
// ---------------------------------------------------------------------------

function createLogger(): Logger {
  const winston = getWinstonLogger();

  return {
    error(message: string, meta?: LogMeta) {
      const safeMessage = redactString(message);
      const safeMeta = redactLogData(meta);
      sentryCaptureError(safeMessage, meta);
      if (winston) {
        winston.error(safeMessage, safeMeta);
      } else {
        console.error(`[ERROR] ${safeMessage}`, safeMeta ?? '');
      }
    },

    warn(message: string, meta?: LogMeta) {
      const safeMessage = redactString(message);
      const safeMeta = redactLogData(meta);
      sentryBreadcrumb('warning', safeMessage, safeMeta);
      if (winston) {
        winston.warn(safeMessage, safeMeta);
      } else {
        console.warn(`[WARN] ${safeMessage}`, safeMeta ?? '');
      }
    },

    info(message: string, meta?: LogMeta) {
      const safeMessage = redactString(message);
      const safeMeta = redactLogData(meta);
      sentryBreadcrumb('info', safeMessage, safeMeta);
      if (winston) {
        winston.info(safeMessage, safeMeta);
      } else {
        console.info(`[INFO] ${safeMessage}`, safeMeta ?? '');
      }
    },

    debug(message: string, meta?: LogMeta) {
      const safeMessage = redactString(message);
      const safeMeta = redactLogData(meta);
      sentryBreadcrumb('debug', safeMessage, safeMeta);
      if (winston) {
        winston.debug(safeMessage, safeMeta);
      } else {
        console.debug(`[DEBUG] ${safeMessage}`, safeMeta ?? '');
      }
    },
  };
}

export const logger: Logger = createLogger();
