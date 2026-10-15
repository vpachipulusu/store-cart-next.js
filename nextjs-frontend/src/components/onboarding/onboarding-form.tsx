'use client';

import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { createStoreAction } from '@/app/actions/onboarding-actions';
import { slugify, type OnboardingInput } from '@/lib/onboarding/schema';

type FieldName = keyof OnboardingInput;
type FieldErrors = Partial<Record<FieldName, string>>;

/** The server ignores the business fields when it reuses an existing business; these only satisfy validation. */
const RESUME_ORGANIZATION_SLUG = 'existing-business';

type OnboardingFormProps = {
  /** Set when a previous attempt created the business but not the store; the form then only asks for the store. */
  resumeOrganizationName?: string;
};

type AddressFieldProps = {
  id: FieldName;
  label: string;
  value: string;
  error?: string;
  autoComplete?: string;
  onChange: (value: string) => void;
};

function Field({ id, label, value, error, autoComplete, onChange }: AddressFieldProps) {
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
 * edits them. Validation and the final say are on the server; a half-finished setup is resumed by submitting again.
 */
export function OnboardingForm({ resumeOrganizationName }: OnboardingFormProps) {
  const router = useRouter();
  const resuming = resumeOrganizationName !== undefined;
  const [values, setValues] = useState<OnboardingInput>({
    organizationName: resumeOrganizationName ?? '',
    organizationSlug: resuming ? RESUME_ORGANIZATION_SLUG : '',
    storeName: '',
    storeSlug: '',
  });
  const [edited, setEdited] = useState<ReadonlySet<FieldName>>(new Set());
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

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

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setFieldErrors({});
    setFormError(null);
    try {
      const result = await createStoreAction(values);
      if (result.success) {
        router.push(`/dashboard/onboarding/status/${encodeURIComponent(result.data.storeId)}`);
        return;
      }
      setFieldErrors(result.fieldErrors ?? {});
      setFormError(result.error ?? null);
    } catch {
      setFormError('We could not set up your store. Please try again.');
    }
    setSubmitting(false);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6" noValidate>
      {resuming ? (
        <p className="text-sm text-muted-foreground">
          Your business{' '}
          <span className="font-medium text-foreground">{resumeOrganizationName}</span> is already
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
      <Button type="submit" disabled={submitting} className="min-h-11 w-full">
        {submitting ? 'Creating your store…' : 'Create my store'}
      </Button>
    </form>
  );
}
