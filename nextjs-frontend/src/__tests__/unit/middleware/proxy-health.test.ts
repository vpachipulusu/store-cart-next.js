import { describe, expect, it } from 'vitest';
import { NextRequest } from 'next/server';
import { proxy } from '@/proxy';

const call = (path: string) => proxy(new NextRequest(`http://localhost${path}`));

describe('proxy /api/health public access', () => {
  it('lets unauthenticated callers reach /api/health', async () => {
    expect((await call('/api/health')).status).toBe(200);
  });

  it('does not make look-alike paths public', async () => {
    expect((await call('/api/healthz-admin')).status).toBe(401);
    expect((await call('/api/health/extra')).status).toBe(401);
  });
});
