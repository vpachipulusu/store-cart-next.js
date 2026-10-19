'use client';

import { useEffect, useRef, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Field } from '@/components/onboarding/onboarding-form';
import { ProvisioningStatus } from '@/components/onboarding/provisioning-status';
import { createAdditionalStoreAction } from '@/app/actions/onboarding-actions';
import { selectStoreAction } from '@/app/actions/store-actions';
import { useToast } from '@/hooks/use-toast';
import {
  SESSION_EXPIRED_MESSAGE,
  slugify,
  type FieldErrors,
  type ResumeInput,
} from '@/lib/onboarding/schema';
import type { StoreStatus } from '@/lib/api/onboarding';

const GENERIC_ERROR = 'We could not set up your store. Please try again.';
const SWITCH_FAILED_TITLE = 'Could not switch store';
const SWITCH_FAILED_FALLBACK = 'Please try again.';

type CreatedStore = { storeId: string; name: string; status: StoreStatus };

type Step =
  | { kind: 'form' }
  | ({ kind: 'provisioning' } & CreatedStore)
  | { kind: 'limit'; message: string };

type NewStoreDialogProps = {
  open: boolean;
  /** The business of the selected store; the server creates the store there (it never takes this from the client). */
  organizationName: string;
  onOpenChange: (open: boolean) => void;
  /** Lets the opener put focus back on its own trigger (the dialog is opened from a menu item that unmounts). */
  onCloseAutoFocus?: (event: Event) => void;
};

type NewStoreFormProps = {
  onCreated: (store: CreatedStore) => void;
  onLimit: (message: string) => void;
};

/** The onboarding store fields (name, suggested address) with the same validation, submitted once at a time. */
function NewStoreForm({ onCreated, onLimit }: NewStoreFormProps) {
  const formRef = useRef<HTMLFormElement>(null);
  const submittingRef = useRef(false);
  const [values, setValues] = useState<ResumeInput>({ storeName: '', storeSlug: '' });
  const [slugEdited, setSlugEdited] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  // After a failed submit, move focus to the first invalid field so keyboard and screen-reader users land on it.
  useEffect(() => {
    if (Object.keys(fieldErrors).length === 0) return;
    formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [fieldErrors]);

  const setName = (storeName: string) =>
    setValues((current) => ({
      storeName,
      storeSlug: slugEdited ? current.storeSlug : slugify(storeName),
    }));

  const setSlug = (storeSlug: string) => {
    setSlugEdited(true);
    setValues((current) => ({ ...current, storeSlug }));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    // A ref, not state: two submits in the same tick both see the same render's state.
    if (submittingRef.current) return;
    submittingRef.current = true;
    setPending(true);
    setFieldErrors({});
    setFormError(null);

    try {
      const result = await createAdditionalStoreAction(values);
      if (result.success) {
        onCreated(result.data);
        return;
      }
      if (result.limitReached) {
        onLimit(result.error ?? GENERIC_ERROR);
        return;
      }
      setFieldErrors(result.fieldErrors ?? {});
      setFormError(
        result.code === 'unauthorized' ? SESSION_EXPIRED_MESSAGE : (result.error ?? null)
      );
    } catch {
      setFormError(GENERIC_ERROR);
    }
    submittingRef.current = false;
    setPending(false);
  };

  return (
    <form ref={formRef} onSubmit={handleSubmit} className="space-y-6" noValidate>
      <Field
        id="storeName"
        label="Store name"
        value={values.storeName}
        error={fieldErrors.storeName}
        onChange={setName}
      />
      <Field
        id="storeSlug"
        label="Store address"
        value={values.storeSlug}
        error={fieldErrors.storeSlug}
        onChange={setSlug}
      />
      {formError && (
        <p role="alert" className="text-sm text-destructive">
          {formError}
        </p>
      )}
      <Button
        type="submit"
        aria-disabled={pending}
        className="min-h-11 w-full aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
      >
        {pending ? 'Creating store…' : 'Create store'}
      </Button>
    </form>
  );
}

/** The plan's store limit (KAN-84 wording): an upgrade prompt, not an error. Focused so it is read out on arrival. */
function StoreLimitNotice({ message }: { message: string }) {
  const noticeRef = useRef<HTMLDivElement>(null);

  useEffect(() => noticeRef.current?.focus(), []);

  return (
    <div
      ref={noticeRef}
      tabIndex={-1}
      role="status"
      className="flex flex-col items-start gap-4 outline-none"
      data-testid="store-limit"
    >
      <p className="text-sm">{message}</p>
      <Button asChild className="min-h-11">
        <Link href="/pricing">See plans</Link>
      </Button>
    </div>
  );
}

/** The dialog's steps. It lives inside the dialog content, which unmounts on close, so each opening starts fresh. */
function NewStoreSteps({ onDone }: { onDone: () => void }) {
  const router = useRouter();
  const { toast } = useToast();
  const [step, setStep] = useState<Step>({ kind: 'form' });
  /** The store is ready but selecting it failed; the user can try again from here (onReady fires only once). */
  const [selectFailed, setSelectFailed] = useState(false);
  const [selecting, setSelecting] = useState(false);

  const reportSwitchFailure = (description?: string) =>
    toast({
      title: SWITCH_FAILED_TITLE,
      description: description ?? SWITCH_FAILED_FALLBACK,
      variant: 'destructive',
    });

  const selectNewStore = async ({ storeId, name }: CreatedStore) => {
    setSelecting(true);
    setSelectFailed(false);
    try {
      const result = await selectStoreAction(storeId);
      if (!result.success) {
        setSelectFailed(true);
        reportSwitchFailure(result.error);
        return;
      }
      router.refresh();
      toast({ title: 'Store ready', description: `Now showing ${name}.` });
      onDone();
    } catch {
      setSelectFailed(true);
      reportSwitchFailure();
    } finally {
      setSelecting(false);
    }
  };

  if (step.kind === 'limit') return <StoreLimitNotice message={step.message} />;
  if (step.kind === 'provisioning') {
    return (
      <div className="flex flex-col items-start gap-4">
        <ProvisioningStatus
          storeId={step.storeId}
          storeName={step.name}
          initialStatus={step.status}
          onReady={() => void selectNewStore(step)}
          variant="dialog"
        />
        {selectFailed ? (
          <Button
            type="button"
            variant="outline"
            aria-disabled={selecting}
            onClick={() => {
              if (!selecting) void selectNewStore(step);
            }}
            className="min-h-11 aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
          >
            Switch to {step.name}
          </Button>
        ) : (
          <p className="text-sm text-muted-foreground">
            Keep this open to switch to the new store when it is ready, or close it and pick the
            store from your store menu later.
          </p>
        )}
      </div>
    );
  }
  return (
    <NewStoreForm
      onCreated={(store) => setStep({ kind: 'provisioning', ...store })}
      onLimit={(message) => setStep({ kind: 'limit', message })}
    />
  );
}

/**
 * "New store" from the dashboard store menu (KAN-254). Creates a store in the organisation of the selected store
 * (decided on the server), follows its setup with the onboarding provisioning status (FAILED keeps Retry setup),
 * and selects it once it is ready.
 */
export function NewStoreDialog({
  open,
  organizationName,
  onOpenChange,
  onCloseAutoFocus,
}: NewStoreDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md" onCloseAutoFocus={onCloseAutoFocus}>
        <DialogHeader>
          <DialogTitle>New store</DialogTitle>
          <DialogDescription>
            Add another store to {organizationName}. Each store has its own products and orders.
          </DialogDescription>
        </DialogHeader>
        <NewStoreSteps onDone={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}
