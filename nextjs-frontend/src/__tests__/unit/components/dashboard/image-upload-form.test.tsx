/** KAN-249: the Add image form validates, uploads with progress, registers, and reports failures. */
import { StrictMode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({
  presignImageUploadAction: vi.fn(),
  addImageAction: vi.fn(),
  putFile: vi.fn(),
}));

vi.mock('@/app/actions/product-actions', () => ({
  presignImageUploadAction: mocks.presignImageUploadAction,
  addImageAction: mocks.addImageAction,
}));
vi.mock('@/lib/products/upload-client', async () => {
  const actual = await vi.importActual<typeof import('@/lib/products/upload-client')>(
    '@/lib/products/upload-client'
  );
  return { ...actual, putFile: mocks.putFile };
});

import { ImageUploadForm } from '@/components/dashboard/products/image-upload-form';
import type { ProductData } from '@/lib/api/products';
import {
  MAX_IMAGE_BYTES,
  TOO_LARGE_MESSAGE,
  WRONG_TYPE_MESSAGE,
} from '@/lib/products/image-upload';
import { NETWORK_UPLOAD_MESSAGE, REJECTED_UPLOAD_MESSAGE } from '@/lib/products/upload-client';

const product = { id: 'p1' } as ProductData;
const updated = { id: 'p1', images: [{ id: 'i2' }] } as unknown as ProductData;
const ticket = {
  success: true,
  data: {
    uploadUrl: 'https://r2.example/x?sig=1',
    headers: { 'Content-Type': 'image/png' },
    key: 'stores/s1/a.png',
  },
};

function pngFile(size = 100) {
  const file = new File(['x'], 'photo.png', { type: 'image/png' });
  Object.defineProperty(file, 'size', { value: size });
  return file;
}

function setup(strict = false) {
  const onUpdated = vi.fn();
  const user = userEvent.setup({ applyAccept: false });
  const form = <ImageUploadForm product={product} onUpdated={onUpdated} />;
  const view = render(strict ? <StrictMode>{form}</StrictMode> : form);
  return { onUpdated, user, view };
}

async function chooseAndSubmit(user: ReturnType<typeof userEvent.setup>, file = pngFile()) {
  await user.upload(screen.getByLabelText('Image file'), file);
  await user.click(screen.getByRole('button', { name: 'Add image' }));
}

describe('ImageUploadForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.presignImageUploadAction.mockResolvedValue(ticket);
    mocks.putFile.mockResolvedValue({ ok: true });
    mocks.addImageAction.mockResolvedValue({ success: true, data: updated });
  });

  it('uploads straight to storage then registers the image and reports the product', async () => {
    const { user, onUpdated } = setup();
    await user.type(screen.getByLabelText('Alt text (optional)'), 'Front');
    await chooseAndSubmit(user);

    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(updated));
    expect(mocks.presignImageUploadAction).toHaveBeenCalledWith('p1', {
      contentType: 'image/png',
      sizeBytes: 100,
    });
    expect(mocks.putFile).toHaveBeenCalledWith(
      ticket.data.uploadUrl,
      ticket.data.headers,
      expect.any(File),
      expect.any(Function),
      expect.any(AbortSignal)
    );
    expect(mocks.addImageAction).toHaveBeenCalledWith('p1', {
      storageKey: 'stores/s1/a.png',
      altText: 'Front',
    });
    expect(screen.getByLabelText('Alt text (optional)')).toHaveValue('');
  });

  it('shows a labelled progress bar and locks the form while uploading', async () => {
    let finish: (value: { ok: true }) => void = () => {};
    mocks.putFile.mockImplementation(
      (_url: string, _headers: unknown, _file: unknown, onProgress: (n: number) => void) => {
        onProgress(40);
        return new Promise((resolve) => (finish = resolve));
      }
    );
    const { user } = setup();
    await chooseAndSubmit(user);

    const bar = await screen.findByTestId('upload-progress');
    expect(bar).toHaveAttribute('value', '40');
    expect(bar).toHaveAccessibleName('Upload progress');
    expect(screen.getByLabelText('Image file')).toBeDisabled();

    finish({ ok: true });
    await waitFor(() => expect(mocks.addImageAction).toHaveBeenCalled());
  });

  it.each([
    ['wrong type', new File(['x'], 'a.gif', { type: 'image/gif' }), WRONG_TYPE_MESSAGE],
    ['too large', pngFile(MAX_IMAGE_BYTES + 1), TOO_LARGE_MESSAGE],
  ])('blocks a %s file with an alert and makes no request', async (_name, file, message) => {
    const { user } = setup();
    await user.upload(screen.getByLabelText('Image file'), file);

    expect(screen.getByRole('alert')).toHaveTextContent(message);
    expect(screen.getByRole('button', { name: 'Add image' })).toBeDisabled();
    expect(mocks.presignImageUploadAction).not.toHaveBeenCalled();
  });

  it('shows the server message when presigning fails and does not upload', async () => {
    mocks.presignImageUploadAction.mockResolvedValue({
      success: false,
      error: 'Too many requests.',
    });
    const { user } = setup();
    await chooseAndSubmit(user);

    expect(await screen.findByRole('alert')).toHaveTextContent('Too many requests.');
    expect(mocks.putFile).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Add image' })).toBeEnabled();
  });

  it.each([
    ['network/CORS', { ok: false, reason: 'network' }, NETWORK_UPLOAD_MESSAGE],
    ['rejected', { ok: false, reason: 'rejected', status: 403 }, REJECTED_UPLOAD_MESSAGE],
  ])('reports a %s upload failure and does not register', async (_name, result, message) => {
    mocks.putFile.mockResolvedValue(result);
    const { user } = setup();
    await chooseAndSubmit(user);

    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(mocks.addImageAction).not.toHaveBeenCalled();
  });

  it('retries registering without uploading again when registration fails', async () => {
    mocks.addImageAction.mockResolvedValueOnce({
      success: false,
      error: 'Image is already attached',
    });
    const { user, onUpdated } = setup();
    await chooseAndSubmit(user);

    expect(await screen.findByRole('alert')).toHaveTextContent(/Image is already attached.*Retry/);
    await user.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(updated));
    expect(mocks.presignImageUploadAction).toHaveBeenCalledTimes(1);
    expect(mocks.putFile).toHaveBeenCalledTimes(1);
    expect(mocks.addImageAction).toHaveBeenCalledTimes(2);
  });

  it('shows a request failed message when presigning throws', async () => {
    mocks.presignImageUploadAction.mockRejectedValue(new Error('boom'));
    const { user } = setup();
    await chooseAndSubmit(user);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The request failed. Please try again.'
    );
    expect(mocks.putFile).not.toHaveBeenCalled();
  });

  it('offers Retry when registration throws, and retries with the same key and alt text', async () => {
    mocks.addImageAction.mockRejectedValueOnce(new Error('boom'));
    const { user, onUpdated } = setup();
    await user.type(screen.getByLabelText('Alt text (optional)'), 'Front');
    await chooseAndSubmit(user);

    expect(await screen.findByRole('alert')).toHaveTextContent(/Retry to add it/);
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(onUpdated).toHaveBeenCalled());
    expect(mocks.addImageAction).toHaveBeenLastCalledWith('p1', {
      storageKey: 'stores/s1/a.png',
      altText: 'Front',
    });
  });

  it('shows no error when the upload was aborted', async () => {
    mocks.putFile.mockResolvedValue({ ok: false, reason: 'aborted' });
    const { user } = setup();
    await chooseAndSubmit(user);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add image' })).toBeEnabled());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(mocks.addImageAction).not.toHaveBeenCalled();
  });

  it('keeps the retry state when the file picker is cancelled', async () => {
    mocks.addImageAction.mockResolvedValueOnce({ success: false, error: 'Nope' });
    const { user } = setup();
    await chooseAndSubmit(user);
    await screen.findByRole('button', { name: 'Retry' });

    fireEvent.change(screen.getByLabelText('Image file'), { target: { files: [] } });
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('announces success and clears the file input', async () => {
    const { user } = setup();
    await chooseAndSubmit(user);
    expect(await screen.findByText('Image added.')).toBeInTheDocument();
    expect((screen.getByLabelText('Image file') as HTMLInputElement).value).toBe('');
  });

  it('uploads under StrictMode (mount, cleanup, mount) instead of silently aborting', async () => {
    const { user, onUpdated } = setup(true);
    await chooseAndSubmit(user);

    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(updated));
    const signal = mocks.putFile.mock.calls[0][4] as AbortSignal;
    expect(signal.aborted).toBe(false);
  });

  it('aborts the transfer on unmount and does not register or update', async () => {
    let finish: (value: unknown) => void = () => {};
    mocks.putFile.mockImplementation(
      (_u: string, _h: unknown, _f: unknown, _p: unknown, signal: AbortSignal) =>
        new Promise((resolve) => {
          finish = resolve;
          signal.addEventListener('abort', () => resolve({ ok: false, reason: 'aborted' }));
        })
    );
    const { user, onUpdated, view } = setup();
    await chooseAndSubmit(user);
    await screen.findByTestId('upload-progress');
    const signal = mocks.putFile.mock.calls[0][4] as AbortSignal;

    view.unmount();
    expect(signal.aborted).toBe(true);
    finish({ ok: true });
    await Promise.resolve();
    expect(mocks.addImageAction).not.toHaveBeenCalled();
    expect(onUpdated).not.toHaveBeenCalled();
  });

  it('does not upload when closed while the link is being requested', async () => {
    let resolveTicket: (value: unknown) => void = () => {};
    mocks.presignImageUploadAction.mockReturnValue(new Promise((r) => (resolveTicket = r)));
    const { user, view } = setup();
    await chooseAndSubmit(user);

    view.unmount();
    resolveTicket(ticket);
    await Promise.resolve();
    expect(mocks.putFile).not.toHaveBeenCalled();
  });

  it('does not call onUpdated when closed while the image is being registered', async () => {
    let resolveAdd: (value: unknown) => void = () => {};
    mocks.addImageAction.mockReturnValue(new Promise((r) => (resolveAdd = r)));
    const { user, onUpdated, view } = setup();
    await chooseAndSubmit(user);
    await waitFor(() => expect(mocks.addImageAction).toHaveBeenCalled());

    view.unmount();
    resolveAdd({ success: true, data: updated });
    await Promise.resolve();
    expect(onUpdated).not.toHaveBeenCalled();
  });

  it('shows an over-long alt text error next to the field', async () => {
    mocks.addImageAction.mockResolvedValue({
      success: false,
      error: 'Check the highlighted fields and try again.',
      fieldErrors: { altText: 'Alt text must be 500 characters or fewer' },
    });
    const { user } = setup();
    await chooseAndSubmit(user);

    expect(await screen.findByText('Alt text must be 500 characters or fewer')).toHaveAttribute(
      'role',
      'alert'
    );
    expect(screen.getByLabelText('Alt text (optional)')).toHaveAttribute('aria-invalid', 'true');
  });
});
