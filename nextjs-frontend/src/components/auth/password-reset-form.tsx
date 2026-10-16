'use client';

import { useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { Button } from '@/components/ui/button';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { resetPassword } from '@/lib/firebase/auth-helpers';
import { AuthFormAlert, FIELD_ERROR_CLASS } from './auth-form-alert';
import { classifyAuthError, NETWORK_ERROR, type AuthFormError } from './auth-form-errors';

const resetPasswordSchema = z.object({
  email: z.string().email('Please enter a valid email address'),
});

type ResetPasswordFormValues = z.infer<typeof resetPasswordSchema>;

export function PasswordResetForm() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<AuthFormError | null>(null);
  const isSubmitting = useRef(false);
  const [success, setSuccess] = useState(false);

  const form = useForm<ResetPasswordFormValues>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: {
      email: '',
    },
  });

  async function onSubmit(data: ResetPasswordFormValues) {
    if (isSubmitting.current) return;
    isSubmitting.current = true;
    try {
      setIsLoading(true);
      setError(null);
      setSuccess(false);

      const { error: resetError } = await resetPassword(data.email);

      const failure = resetError ? classifyAuthError(resetError, 'reset') : null;
      // A missing account looks exactly like success, so the outcome never reveals whether it exists.
      if (failure && failure.kind !== 'account-missing') {
        setError(failure);
        return;
      }

      setSuccess(true);
      form.reset();
    } catch (error) {
      setError(NETWORK_ERROR);
      console.error('Password reset error:', error);
    } finally {
      isSubmitting.current = false;
      setIsLoading(false);
    }
  }

  return (
    <Form {...form}>
      <form
        onSubmit={(event) => form.handleSubmit(onSubmit)(event)}
        className="space-y-4"
        noValidate
        aria-busy={isLoading}
      >
        {error && <AuthFormAlert error={error} />}

        {/* The live region stays mounted so screen readers announce the text when it is filled. */}
        <div role="status">
          {success && (
            <p className="rounded-md bg-green-50 p-3 text-sm text-green-800 dark:bg-green-900/20 dark:text-green-400">
              If an account exists for that email, we have sent a reset link. Check your inbox for
              further instructions.
            </p>
          )}
        </div>

        <FormField
          control={form.control}
          name="email"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Email</FormLabel>
              <FormControl>
                <Input
                  placeholder="name@example.com"
                  type="email"
                  autoComplete="email"
                  disabled={isLoading}
                  className={FIELD_ERROR_CLASS}
                  {...field}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />

        <Button type="submit" className="w-full" disabled={isLoading}>
          {isLoading ? (
            <>
              <div
                aria-hidden="true"
                className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
              />
              Sending reset link...
            </>
          ) : (
            'Send Reset Link'
          )}
        </Button>
      </form>
    </Form>
  );
}
