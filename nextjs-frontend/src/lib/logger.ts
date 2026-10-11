import * as Sentry from '@sentry/nextjs';

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
      defaultMeta: { service: 'saas-boilerplate' },
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

function sentryCaptureError(message: string, meta?: LogMeta): void {
  setImmediate(() => {
    try {
      const normalized = normalizeMeta(meta);
      const error =
        meta instanceof Error
          ? meta
          : normalized?.error instanceof Error
            ? normalized.error
            : new Error(message);
      Sentry.captureException(error, { extra: normalized });
    } catch {
      // Sentry not initialized or DSN not set — silently skip
    }
  });
}

function sentryBreadcrumb(
  level: 'warning' | 'info' | 'debug',
  message: string,
  meta?: LogMeta
): void {
  setImmediate(() => {
    try {
      Sentry.addBreadcrumb({
        level,
        message,
        data: normalizeMeta(meta) as Record<string, unknown> | undefined,
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
      sentryCaptureError(message, meta);
      if (winston) {
        winston.error(message, meta);
      } else {
        console.error(`[ERROR] ${message}`, meta ?? '');
      }
    },

    warn(message: string, meta?: LogMeta) {
      sentryBreadcrumb('warning', message, meta);
      if (winston) {
        winston.warn(message, meta);
      } else {
        console.warn(`[WARN] ${message}`, meta ?? '');
      }
    },

    info(message: string, meta?: LogMeta) {
      sentryBreadcrumb('info', message, meta);
      if (winston) {
        winston.info(message, meta);
      } else {
        console.info(`[INFO] ${message}`, meta ?? '');
      }
    },

    debug(message: string, meta?: LogMeta) {
      sentryBreadcrumb('debug', message, meta);
      if (winston) {
        winston.debug(message, meta);
      } else {
        console.debug(`[DEBUG] ${message}`, meta ?? '');
      }
    },
  };
}

export const logger: Logger = createLogger();
