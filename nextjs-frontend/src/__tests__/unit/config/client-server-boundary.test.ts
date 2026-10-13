// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { CURRENCIES } from '@/config/currencies';

const SRC_DIR = path.resolve(__dirname, '../../..');
const CLIENT_DIRECTIVE = /^\s*['"]use client['"]/;
const SERVER_ONLY_IMPORT =
  /from\s+['"]@\/(config\/subscriptions|lib\/db\/[^'"]+|lib\/api\/server|lib\/logger|lib\/stripe\/[^'"]+|lib\/firebase\/admin)['"]/g;

function listSourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const fullPath = path.join(dir, entry);
    if (statSync(fullPath).isDirectory()) {
      return entry === '__tests__' ? [] : listSourceFiles(fullPath);
    }
    return /\.(ts|tsx)$/.test(entry) ? [fullPath] : [];
  });
}

describe('Client/server import boundary', () => {
  describe('Given every client component in src', () => {
    it('should not import server-only modules', () => {
      const violations = listSourceFiles(SRC_DIR)
        .filter((file) => CLIENT_DIRECTIVE.test(readFileSync(file, 'utf8')))
        .flatMap((file) =>
          [...readFileSync(file, 'utf8').matchAll(SERVER_ONLY_IMPORT)].map(
            (match) => `${path.relative(SRC_DIR, file)} imports @/${match[1]}`
          )
        );

      expect(violations).toEqual([]);
    });
  });
});

describe('Currencies config', () => {
  describe('Given the client-safe CURRENCIES list', () => {
    it('should include USD with the dollar symbol', () => {
      expect(CURRENCIES.find((c) => c.code === 'USD')?.symbol).toBe('$');
    });

    it('should have unique currency codes', () => {
      const codes = CURRENCIES.map((c) => c.code);
      expect(new Set(codes).size).toBe(codes.length);
    });
  });
});
