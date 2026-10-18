/**
 * Browser side of a direct image upload (KAN-249). `fetch` has no upload progress, so this uses XMLHttpRequest.
 * The presigned URL carries a credential in its query string: it is only ever passed to `xhr.open`, never logged
 * or put in an error message. A request error without a status is what a missing or wrong bucket CORS policy
 * looks like to script, so it gets one combined "network or storage CORS" message.
 */
export type UploadFailure = 'network' | 'rejected' | 'aborted';

export type UploadResult = { ok: true } | { ok: false; reason: UploadFailure; status?: number };

export const NETWORK_UPLOAD_MESSAGE =
  'The upload could not reach storage. Check your connection and try again. If it keeps failing, storage may not allow uploads from this site (CORS) or the upload link may have expired.';
export const REJECTED_UPLOAD_MESSAGE =
  'Storage rejected the upload. The link may have expired, so choose the image again.';

export function uploadFailureMessage(reason: UploadFailure): string {
  return reason === 'network' ? NETWORK_UPLOAD_MESSAGE : REJECTED_UPLOAD_MESSAGE;
}

export function putFile(
  url: string,
  headers: Readonly<Record<string, string>>,
  file: Blob,
  onProgress: (percent: number) => void,
  signal?: AbortSignal
): Promise<UploadResult> {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    const finish = (result: UploadResult) => {
      signal?.removeEventListener('abort', onAbort);
      resolve(result);
    };
    const onAbort = () => xhr.abort();

    try {
      xhr.open('PUT', url);
      for (const [name, value] of Object.entries(headers)) xhr.setRequestHeader(name, value);
    } catch {
      // A malformed URL or header from the ticket: fail with a message instead of rejecting.
      return finish({ ok: false, reason: 'network' });
    }
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      }
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? finish({ ok: true })
        : finish({ ok: false, reason: 'rejected', status: xhr.status });
    xhr.onerror = () => finish({ ok: false, reason: 'network' });
    xhr.ontimeout = () => finish({ ok: false, reason: 'network' });
    xhr.onabort = () => finish({ ok: false, reason: 'aborted' });

    if (signal?.aborted) return finish({ ok: false, reason: 'aborted' });
    signal?.addEventListener('abort', onAbort, { once: true });
    xhr.send(file);
  });
}
