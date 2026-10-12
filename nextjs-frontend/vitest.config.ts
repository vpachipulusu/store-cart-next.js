import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    globals: true,
    exclude: ['**/node_modules/**', '**/dist/**', '**/e2e/**', '**/*.spec.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      include: [
        'src/lib/**/*.{ts,tsx}',
        'src/components/**/*.{ts,tsx}',
        'src/app/actions/**/*.{ts,tsx}',
      ],
      exclude: [
        'src/**/*.d.ts',
        'src/**/*.test.{ts,tsx}',
        'src/**/*.spec.{ts,tsx}',
        'src/**/__tests__/e2e/**',
      ],
      // Coverage ratchet (KAN-27, PO decision on KAN-139): the thresholds are the
      // measured baseline, so CI fails if coverage drops. Raise them towards the
      // 80% target as tests are added, and never lower them. To raise them to the
      // current values in one step, run:
      //   COVERAGE_RATCHET=1 npm run test:coverage
      // (Vitest rewrites the numbers below when coverage is higher.)
      thresholds: {
        autoUpdate: process.env.COVERAGE_RATCHET === '1',
        branches: 29.87,
        functions: 6.33,
        lines: 5.07,
        statements: 5.07,
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
});
