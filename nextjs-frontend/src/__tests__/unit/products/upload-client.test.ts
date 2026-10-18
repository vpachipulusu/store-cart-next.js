/** KAN-249: the browser PUT reports progress and maps failures without leaking the presigned URL. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  NETWORK_UPLOAD_MESSAGE,
  UPLOAD_TIMEOUT_MS,
  putFile,
  REJECTED_UPLOAD_MESSAGE,
  uploadFailureMessage,
} from '@/lib/products/upload-client';

class FakeXhr {
  static last: FakeXhr;
  method = '';
  url = '';
  headers: Record<string, string> = {};
  body: unknown;
  status = 0;
  timeout = 0;
  upload: { onprogress: ((event: unknown) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  onabort: (() => void) | null = null;
  constructor() {
    FakeXhr.last = this;
  }
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }
  send(body: unknown) {
    this.body = body;
  }
  abort() {
    this.onabort?.();
  }
}

const URL_WITH_SECRET = 'https://r2.example/stores/s1/a.png?X-Amz-Signature=secret';

describe('putFile', () => {
  beforeEach(() => vi.stubGlobal('XMLHttpRequest', FakeXhr));
  afterEach(() => vi.unstubAllGlobals());

  it('PUTs the file with the presigned headers, reports progress and resolves ok on 2xx', async () => {
    const file = new Blob(['x'], { type: 'image/png' });
    const progress = vi.fn();
    const promise = putFile(URL_WITH_SECRET, { 'Content-Type': 'image/png' }, file, progress);
    const xhr = FakeXhr.last;

    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 200 });
    xhr.upload.onprogress?.({ lengthComputable: false, loaded: 1, total: 0 });
    xhr.status = 200;
    xhr.onload?.();

    await expect(promise).resolves.toEqual({ ok: true });
    expect(xhr.method).toBe('PUT');
    expect(xhr.url).toBe(URL_WITH_SECRET);
    expect(xhr.headers).toEqual({ 'Content-Type': 'image/png' });
    expect(xhr.body).toBe(file);
    expect(xhr.timeout).toBe(UPLOAD_TIMEOUT_MS);
    expect(progress).toHaveBeenCalledTimes(1);
    expect(progress).toHaveBeenCalledWith(25);
  });

  it('resolves rejected with the status for a non-2xx answer', async () => {
    const promise = putFile(URL_WITH_SECRET, {}, new Blob(['x']), vi.fn());
    FakeXhr.last.status = 403;
    FakeXhr.last.onload?.();
    await expect(promise).resolves.toEqual({ ok: false, reason: 'rejected', status: 403 });
  });

  it.each(['onerror', 'ontimeout'] as const)('treats %s as a network failure', async (hook) => {
    const promise = putFile(URL_WITH_SECRET, {}, new Blob(['x']), vi.fn());
    FakeXhr.last[hook]?.();
    await expect(promise).resolves.toEqual({ ok: false, reason: 'network' });
  });

  it('aborts when the signal fires, and does not send when it already fired', async () => {
    const controller = new AbortController();
    const promise = putFile(URL_WITH_SECRET, {}, new Blob(['x']), vi.fn(), controller.signal);
    controller.abort();
    await expect(promise).resolves.toEqual({ ok: false, reason: 'aborted' });

    const already = await putFile(URL_WITH_SECRET, {}, new Blob(['x']), vi.fn(), controller.signal);
    expect(already).toEqual({ ok: false, reason: 'aborted' });
  });

  it('fails with a network result instead of throwing when a header is invalid', async () => {
    vi.stubGlobal(
      'XMLHttpRequest',
      class extends FakeXhr {
        setRequestHeader(): void {
          throw new Error('bad header');
        }
      }
    );
    await expect(
      putFile(URL_WITH_SECRET, { 'Bad Header': 'x' }, new Blob(['x']), vi.fn())
    ).resolves.toEqual({ ok: false, reason: 'network' });
  });

  it('keeps the presigned URL out of the failure messages', () => {
    for (const reason of ['network', 'rejected', 'aborted'] as const) {
      expect(uploadFailureMessage(reason)).not.toContain('X-Amz');
    }
    expect(uploadFailureMessage('network')).toBe(NETWORK_UPLOAD_MESSAGE);
    expect(uploadFailureMessage('rejected')).toBe(REJECTED_UPLOAD_MESSAGE);
  });
});
