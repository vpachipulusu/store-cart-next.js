import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

interface TwoFactorCodeFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** Error text shown under the field; also marks the input invalid and links it with aria-describedby. */
  error?: string | null;
  /** Id of an error element rendered elsewhere (e.g. the dialog's alert); linked and marks the input invalid. */
  describedBy?: string;
}

/** Six-digit authenticator code: one 56px input, numeric keypad on phones, one-time-code autofill. */
export function TwoFactorCodeField({
  id,
  label,
  value,
  onChange,
  error,
  describedBy,
}: TwoFactorCodeFieldProps) {
  const errorId = `${id}-error`;

  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={6}
        className="h-14 text-center font-mono text-xl tracking-[0.5em]"
        value={value}
        aria-invalid={error || describedBy ? true : undefined}
        aria-describedby={error ? errorId : describedBy}
        onChange={(event) => onChange(event.target.value.replace(/\D/g, ''))}
      />
      {error && (
        <p id={errorId} className="mt-1.5 text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
