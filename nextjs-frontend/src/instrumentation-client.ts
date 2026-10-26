import * as Sentry from '@sentry/nextjs';
import { INVITE_TOKEN_SENTRY_HOOKS } from '@/lib/sentry/scrub-invite-token';

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  enabled: !!process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NODE_ENV,

  // Performance: low sample rate in production
  tracesSampleRate: process.env.NODE_ENV === 'production' ? 0.1 : 1.0,

  // Invitation links carry a single-use token in the path (KAN-62).
  ...INVITE_TOKEN_SENTRY_HOOKS,

  // Session Replay disabled (heavy on performance)
  replaysSessionSampleRate: 0,
  replaysOnErrorSampleRate: 0,
});

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
