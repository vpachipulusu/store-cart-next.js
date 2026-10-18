'use client';

import { useEffect, useRef, useState, type FormEvent } from 'react';
import { addImageAction, presignImageUploadAction } from '@/app/actions/product-actions';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { ProductData } from '@/lib/api/products';
import { ALT_TEXT_MAX_LENGTH, IMAGE_ACCEPT, imageFileError } from '@/lib/products/image-upload';
import { putFile, uploadFailureMessage } from '@/lib/products/upload-client';
import { Field } from './field';

type Stage = 'idle' | 'preparing' | 'uploading' | 'saving';

const STAGE_TEXT: Record<Stage, string> = {
  idle: '',
  preparing: 'Preparing upload…',
  uploading: 'Uploading…',
  saving: 'Adding image to the product…',
};

const REQUEST_FAILED = 'The request failed. Please try again.';
const RETRY_HINT = 'The file is uploaded; use Retry to add it to the product.';

/**
 * "Add image" (KAN-249). Order: validate the file here, ask the server for a presigned URL, PUT the file straight
 * to storage (never through the app or the API), then register the object on the product. If registration fails
 * the object is already uploaded, so the form offers to retry registering it instead of uploading again; it
 * cannot delete the object (there is no delete route), and an unregistered one is harmless and unreferenced.
 */
export function ImageUploadForm({
  product,
  onUpdated,
}: {
  product: ProductData;
  onUpdated: (product: ProductData) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [altText, setAltText] = useState('');
  const [fileError, setFileError] = useState<string | null>(null);
  const [altError, setAltError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage>('idle');
  const [percent, setPercent] = useState<number | null>(null);
  const [added, setAdded] = useState(false);
  const [uploadedKey, setUploadedKey] = useState<string | null>(null);
  const [inputKey, setInputKey] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const wasBusy = useRef(false);
  const refocus = useRef<'file' | 'button'>('button');
  const busy = stage !== 'idle';

  // Set on mount, not at creation: StrictMode runs mount, cleanup, mount, so state must be rebuilt by the effect.
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      abortRef.current?.abort();
    };
  }, []);

  // A disabled control drops keyboard focus, so put it back when the work ends.
  useEffect(() => {
    if (busy) {
      wasBusy.current = true;
      return;
    }
    if (!wasBusy.current) return;
    wasBusy.current = false;
    (refocus.current === 'file' ? fileRef : buttonRef).current?.focus();
  }, [busy]);

  function reset() {
    setFile(null);
    setAltText('');
    setUploadedKey(null);
    setPercent(null);
    setInputKey((key) => key + 1);
  }

  function chooseFile(chosen: File | null) {
    if (!chosen) return; // a cancelled picker must not drop a pending retry
    setError(null);
    setAdded(false);
    setUploadedKey(null);
    setFile(chosen);
    setFileError(imageFileError(chosen));
  }

  async function register(storageKey: string) {
    setStage('saving');
    let response: Awaited<ReturnType<typeof addImageAction>>;
    try {
      response = await addImageAction(product.id, { storageKey, altText });
    } catch {
      if (!mounted.current) return;
      setUploadedKey(storageKey);
      setError(`${REQUEST_FAILED} ${RETRY_HINT}`);
      return;
    }
    if (!mounted.current) return;
    if (response.success) {
      reset();
      setAdded(true);
      refocus.current = 'file';
      onUpdated(response.data);
      return;
    }
    setUploadedKey(storageKey);
    if (response.fieldErrors?.altText) setAltError(response.fieldErrors.altText);
    else setError(`${response.error} ${RETRY_HINT}`);
  }

  async function upload(chosen: File) {
    setStage('preparing');
    setPercent(null);
    refocus.current = 'button';
    let ticket: Awaited<ReturnType<typeof presignImageUploadAction>>;
    try {
      ticket = await presignImageUploadAction(product.id, {
        contentType: chosen.type,
        sizeBytes: chosen.size,
      });
    } catch {
      if (mounted.current) setError(REQUEST_FAILED);
      return;
    }
    if (!mounted.current) return; // the editor was closed while the link was being requested
    if (!ticket.success) {
      setError(ticket.error);
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setStage('uploading');
    const result = await putFile(
      ticket.data.uploadUrl,
      ticket.data.headers,
      chosen,
      setPercent,
      controller.signal
    );
    abortRef.current = null;
    if (!mounted.current) return;
    if (!result.ok) {
      if (result.reason !== 'aborted') setError(uploadFailureMessage(result.reason));
      return;
    }
    await register(ticket.data.key);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setError(null);
    setAltError(null);
    setAdded(false);
    if (!file) {
      setFileError('Choose an image to upload.');
      return;
    }
    const invalid = imageFileError(file);
    if (invalid) {
      setFileError(invalid);
      return;
    }
    try {
      if (uploadedKey) await register(uploadedKey);
      else await upload(file);
    } finally {
      if (mounted.current) setStage('idle');
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3 rounded-lg border p-3" aria-label="Add image">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field
          id="image-file"
          label="Image file"
          hint="JPEG, PNG or WebP, up to 10 MB."
          error={fileError ?? undefined}
        >
          {(describedBy) => (
            <Input
              key={inputKey}
              ref={fileRef}
              id="image-file"
              type="file"
              accept={IMAGE_ACCEPT}
              disabled={busy}
              aria-invalid={fileError ? true : undefined}
              aria-describedby={describedBy}
              onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
            />
          )}
        </Field>
        <Field id="image-alt" label="Alt text (optional)" error={altError ?? undefined}>
          {(describedBy) => (
            <Input
              id="image-alt"
              value={altText}
              maxLength={ALT_TEXT_MAX_LENGTH}
              disabled={busy}
              aria-invalid={altError ? true : undefined}
              aria-describedby={describedBy}
              onChange={(event) => setAltText(event.target.value)}
            />
          )}
        </Field>
      </div>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div aria-live="polite" className="space-y-1.5">
        {busy && <p className="text-sm text-muted-foreground">{STAGE_TEXT[stage]}</p>}
        {added && !busy && <p className="text-sm">Image added.</p>}
        {stage === 'uploading' && (
          <progress
            value={percent ?? undefined}
            max={100}
            aria-label="Upload progress"
            className="h-2 w-full"
            data-testid="upload-progress"
          />
        )}
      </div>
      <Button ref={buttonRef} type="submit" disabled={busy || !file || fileError !== null}>
        {busy ? 'Working…' : uploadedKey ? 'Retry' : 'Add image'}
      </Button>
    </form>
  );
}
