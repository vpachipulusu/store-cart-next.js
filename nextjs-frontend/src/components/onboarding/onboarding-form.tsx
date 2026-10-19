'use client';

import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { createStoreAction } from '@/app/actions/onboarding-actions';
import {
  SESSION_EXPIRED_MESSAGE,
  slugify,
  type FieldErrors,
  type FieldName,
  type OnboardingInput,
  type OnboardingSubmission,
} from '@/lib/onboarding/schema';

/** If the navigation to the status screen has not happened by then, the button works again. */
export const PUSH_STALL_MS = 10000;
const GENERIC_ERROR = 'We could not set up your store. Please try again.';

type OnboardingFormProps = {
  /** Set when a previous attempt created the business but not the store; the form then only asks for the store. */
  resumeOrganizationName?: string;
};

export type FieldProps = {
  id: FieldName;
  label: string;
  value: string;
  error?: string;
  autoComplete?: string;
  onChange: (value: string) => void;
};

/** A labelled onboarding input with its error; also used by the dashboard "New store" dialog (KAN-254). */
export function Field({ id, label, value, error, autoComplete, onChange }: FieldProps) {
  const errorId = `${id}-error`;
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        name={id}
        value={value}
        autoComplete={autoComplete ?? 'off'}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        onChange={(event) => onChange(event.target.value)}
        required
      />
      {error && (
        <p id={errorId} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * Collects the business and first store (KAN-60). Addresses (slugs) are suggested from the names until the user
 * edits them. Validation and the final say are on the server. When the business exists without a store (from an
 * earlier attempt, or because this attempt created it and the store step failed) the form drops the business
 * fields and submits a store-only request, so a retry resumes instead of creating a second business.
 */
export function OnboardingForm({ resumeOrganizationName }: OnboardingFormProps) {
  const router = useRouter();
  const formRef = useRef<HTMLFormElement>(null);
  const submittingRef = useRef(false);
  const createdStoreIdRef = useRef<string | undefined>(undefined);
  const stallTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [resumeName, setResumeName] = useState(resumeOrganizationName);
  const [values, setValues] = useState<OnboardingInput>({
    organizationName: '',
    organizationSlug: '',
    storeName: '',
    storeSlug: '',
  });
  const [edited, setEdited] = useState<ReadonlySet<FieldName>>(new Set());
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const resuming = resumeName !== undefined;

  useEffect(() => () => clearTimeout(stallTimerRef.current), []);

  // After a failed submit, move focus to the first invalid field so keyboard and screen-reader users land on it.
  useEffect(() => {
    if (Object.keys(fieldErrors).length === 0) return;
    formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [fieldErrors]);

  const setName = (
    nameField: 'organizationName' | 'storeName',
    slugField: FieldName,
    value: string
  ) => {
    setValues((current) => ({
      ...current,
      [nameField]: value,
      ...(edited.has(slugField) ? {} : { [slugField]: slugify(value) }),
    }));
  };

  const setSlug = (field: FieldName, value: string) => {
    setEdited((current) => new Set(current).add(field));
    setValues((current) => ({ ...current, [field]: value }));
  };

  const finish = () => {
    submittingRef.current = false;
    setPending(false);
  };

  const goToStatus = (storeId: string) => {
    router.push(`/dashboard/onboarding/status/${encodeURIComponent(storeId)}`);
    // Stay "pending" while navigating, but never forever if the navigation stalls.
    stallTimerRef.current = setTimeout(finish, PUSH_STALL_MS);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    // A ref, not state: two submits in the same tick both see the same render's state.
    if (submittingRef.current) return;
    submittingRef.current = true;
    setPending(true);
    // The store already exists (the navigation stalled): go on to the status screen, never create it twice.
    if (createdStoreIdRef.current) {
      goToStatus(createdStoreIdRef.current);
      return;
    }
    setFieldErrors({});
    setFormError(null);

    const submission: OnboardingSubmission = resuming
      ? { mode: 'resume', storeName: values.storeName, storeSlug: values.storeSlug }
      : { mode: 'new', ...values };

    try {
      const result = await createStoreAction(submission);
      if (result.success) {
        createdStoreIdRef.current = result.data.storeId;
        goToStatus(result.data.storeId);
        return;
      }
      if (result.organizationCreated && !resuming) setResumeName(values.organizationName);
      setFieldErrors(result.fieldErrors ?? {});
      setFormError(
        result.code === 'unauthorized' ? SESSION_EXPIRED_MESSAGE : (result.error ?? null)
      );
    } catch {
      setFormError(GENERIC_ERROR);
    }
    finish();
  };

  return (
    <form ref={formRef} onSubmit={handleSubmit} className="space-y-6" noValidate>
      {resuming ? (
        <p className="text-sm text-muted-foreground">
          Your business <span className="font-medium text-foreground">{resumeName}</span> is already
          created. Finish by adding your first store.
        </p>
      ) : (
        <>
          <Field
            id="organizationName"
            label="Business name"
            value={values.organizationName}
            error={fieldErrors.organizationName}
            autoComplete="organization"
            onChange={(value) => setName('organizationName', 'organizationSlug', value)}
          />
          <Field
            id="organizationSlug"
            label="Business address"
            value={values.organizationSlug}
            error={fieldErrors.organizationSlug}
            onChange={(value) => setSlug('organizationSlug', value)}
          />
        </>
      )}
      <Field
        id="storeName"
        label="Store name"
        value={values.storeName}
        error={fieldErrors.storeName}
        onChange={(value) => setName('storeName', 'storeSlug', value)}
      />
      <Field
        id="storeSlug"
        label="Store address"
        value={values.storeSlug}
        error={fieldErrors.storeSlug}
        onChange={(value) => setSlug('storeSlug', value)}
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
        {pending ? 'Creating your store…' : 'Create my store'}
      </Button>
    </form>
  );
}
