// ESLint flat config (ESLint 9). Replaces the legacy .eslintrc.json, which
// `next lint` used to load; Next 16 removed `next lint`, so `npm run lint`
// now runs `eslint .` directly. See https://nextjs.org/docs/app/api-reference/config/eslint
import { defineConfig, globalIgnores } from 'eslint/config';
import nextVitals from 'eslint-config-next/core-web-vitals';
import nextTs from 'eslint-config-next/typescript';

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores([
    '.next/**',
    '.next-e2e/**',
    '.next-e2e-dev/**',
    'out/**',
    'build/**',
    'node_modules/**',
    'coverage/**',
    'playwright-report/**',
    'test-results/**',
    'logs/**',
    'public/**',
    'next-env.d.ts',
  ]),
  {
    rules: {
      // Carried over from .eslintrc.json.
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
    },
  },
]);
