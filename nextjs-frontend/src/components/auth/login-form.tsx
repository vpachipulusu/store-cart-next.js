'use client';

import { useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
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
import { signInWithEmail } from '@/lib/firebase/auth-helpers';
import { verifyTokenAction } from '@/app/actions/auth-actions';
import { AuthFormAlert, FIELD_ERROR_CLASS } from './auth-form-alert';
import { classifyAuthError, NETWORK_ERROR, type AuthFormError } from './auth-form-errors';

const loginSchema = z.object({
  email: z.string().email('Please enter a valid email address'),
  password: z.string().min(6, 'Password must be at least 6 characters'),
});

type LoginFormValues = z.infer<typeof loginSchema>;

export function LoginForm() {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<AuthFormError | null>(null);
  const isSubmitting = useRef(false);

  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: {
      email: '',
      password: '',
    },
  });

  async function onSubmit(data: LoginFormValues) {
    if (isSubmitting.current) return;
    isSubmitting.current = true;
    let redirected = false;
    try {
      setIsLoading(true);
      setError(null);

      const {
        user,
        idToken,
        error: signInError,
      } = await signInWithEmail(data.email, data.password);

      if (signInError) {
        setError(classifyAuthError(signInError, 'sign-in'));
        return;
      }

      if (user && idToken) {
        // Create session on server
        const result = await verifyTokenAction(idToken);

        if (!result.success) {
          setError(classifyAuthError(result.error, 'sign-in'));
          return;
        }

        redirected = true;
        router.push('/dashboard');
        router.refresh();
      }
    } catch (error) {
      setError(NETWORK_ERROR);
      console.error('Login error:', error);
    } finally {
      // Stay locked while the redirect is in flight so a second submit cannot run.
      if (!redirected) {
        isSubmitting.current = false;
        setIsLoading(false);
      }
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

        <FormField
          control={form.control}
          name="password"
          render={({ field }) => (
            <FormItem>
              <div className="flex items-center justify-between">
                <FormLabel>Password</FormLabel>
                <Link
                  href="/reset-password"
                  className="text-sm text-muted-foreground hover:text-primary"
                >
                  Forgot password?
                </Link>
              </div>
              <FormControl>
                <Input
                  placeholder="Enter your password"
                  type="password"
                  autoComplete="current-password"
                  disabled={isLoading}
                  className={FIELD_ERROR_CLASS}
                  {...field}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />

        <Button type="submit" variant="accent" className="w-full" disabled={isLoading}>
          {isLoading ? (
            <>
              <div
                aria-hidden="true"
                className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
              />
              Signing in...
            </>
          ) : (
            'Sign In'
          )}
        </Button>
      </form>
    </Form>
  );
}
