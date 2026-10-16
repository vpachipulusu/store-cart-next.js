import Link from 'next/link';
import { KeyRound } from 'lucide-react';
import { PasswordResetForm } from '@/components/auth/password-reset-form';
import { AUTH_LINK_CLASS, AuthHeading, AuthIconTile } from '../_components/auth-shared';

export const metadata = {
  title: 'Reset Password',
  description: 'Reset your password',
};

export default function ResetPasswordPage() {
  return (
    <section className="space-y-6">
      <header className="space-y-2 text-center">
        <AuthIconTile>
          <KeyRound className="h-6 w-6" aria-hidden="true" />
        </AuthIconTile>
        <AuthHeading>Reset your password</AuthHeading>
        <p className="text-sm text-muted-foreground">
          Enter your email address and we&apos;ll send you a link to reset your password
        </p>
      </header>
      <PasswordResetForm />
      <p className="text-center text-sm text-muted-foreground">
        Remember your password?{' '}
        <Link href="/login" className={AUTH_LINK_CLASS}>
          Sign in
        </Link>
      </p>
    </section>
  );
}
