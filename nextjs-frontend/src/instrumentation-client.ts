import * as Sentry from '@sentry/nextjs';
import { scrubInviteTokens } from '@/lib/sentry/scrub-invite-token';

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  enabled: !!process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NODE_ENV,

  // Performance: low sample rate in production
  tracesSampleRate: process.env.NODE_ENV === 'production' ? 0.1 : 1.0,

  // Invitation links carry a single-use token in the path (KAN-62).
  beforeSend: scrubInviteTokens,
  beforeSendTransaction: scrubInviteTokens,
  beforeBreadcrumb: scrubInviteTokens,

  // Session Replay disabled (heavy on performance)
  replaysSessionSampleRate: 0,
  replaysOnErrorSampleRate: 0,
});

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
