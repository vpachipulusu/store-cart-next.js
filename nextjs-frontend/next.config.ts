import type { NextConfig } from 'next';
import { withSentryConfig } from '@sentry/nextjs';

const nextConfig: NextConfig = {
  // Compile out the test override from ordinary production artifacts, even if someone
  // sets the runtime switch later. Only the dedicated local E2E scripts opt in.
  env: {
    E2E_RATE_LIMIT_TEST_MODE:
      process.env.E2E_RATE_LIMIT_TEST_MODE === '1' &&
      ['.next-e2e', '.next-e2e-dev'].includes(process.env.NEXT_DIST_DIR ?? '') &&
      !process.env.VERCEL &&
      !process.env.VERCEL_ENV
        ? '1'
        : '0',
  },
  // e2e builds use their own folder (scripts/e2e-build.mjs sets NEXT_DIST_DIR=.next-e2e), so they never replace the
  // developer's normal .next build, which uses the dev Firebase project.
  distDir: process.env.NEXT_DIST_DIR || '.next',
  reactStrictMode: true,
  serverExternalPackages: ['winston', 'winston-daily-rotate-file'],
  webpack: (config) => {
    // Prevent webpack from watching the logs/ directory.
    // Without this, every Winston file write triggers a full HMR recompile.
    // Must be a string-only array — webpack 5 schema rejects RegExp entries here.
    config.watchOptions = {
      ...config.watchOptions,
      ignored: ['**/node_modules/**', '**/.git/**', '**/logs/**'],
    };
    return config;
  },
  experimental: {
    serverActions: {
      bodySizeLimit: '2mb',
    },
  },
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'lh3.googleusercontent.com',
      },
      {
        protocol: 'https',
        hostname: 'avatars.githubusercontent.com',
      },
    ],
  },
};

export default withSentryConfig(nextConfig, {
  silent: true,
  sourcemaps: {
    disable: !process.env.SENTRY_AUTH_TOKEN,
  },
});
