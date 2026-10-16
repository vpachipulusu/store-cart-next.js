import Link from 'next/link';
import { LoginForm } from '@/components/auth/login-form';
import { OAuthButtons } from '@/components/auth/oauth-buttons';
import { AUTH_LINK_CLASS, AuthDivider, AuthHeading } from '../_components/auth-shared';

export const metadata = {
  title: 'Login',
  description: 'Login to your account',
};

export default function LoginPage() {
  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <AuthHeading>Welcome back</AuthHeading>
        <p className="text-sm text-muted-foreground">Sign in to your account to continue</p>
      </header>
      <div className="space-y-4">
        <OAuthButtons />
        <AuthDivider>Or continue with email</AuthDivider>
        <LoginForm />
      </div>
      <p className="text-center text-sm text-muted-foreground">
        Don&apos;t have an account?{' '}
        <Link href="/signup" className={AUTH_LINK_CLASS}>
          Sign up
        </Link>
      </p>
    </section>
  );
}
