import Link from 'next/link';
import { SignupForm } from '@/components/auth/signup-form';
import { OAuthButtons } from '@/components/auth/oauth-buttons';
import { AUTH_LINK_CLASS, AuthDivider, AuthHeading } from '../_components/auth-shared';

export const metadata = {
  title: 'Sign Up',
  description: 'Create a new account',
};

export default async function SignupPage({
  searchParams,
}: {
  searchParams: Promise<{ plan?: string }>;
}) {
  const params = await searchParams;
  const selectedPlan = params.plan;

  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <AuthHeading>Create an account</AuthHeading>
        <p className="text-sm text-muted-foreground">Enter your information to get started</p>
        {selectedPlan && (
          <p className="pt-1">
            <span className="inline-flex min-h-6 max-w-full items-center truncate rounded-full bg-secondary px-3 py-0.5 text-[0.8125rem] font-semibold capitalize text-accent-ink">
              Selected Plan: {selectedPlan}
            </span>
          </p>
        )}
      </header>
      <div className="space-y-4">
        <OAuthButtons />
        <AuthDivider>Or continue with email</AuthDivider>
        <SignupForm selectedPlan={selectedPlan} />
      </div>
      <p className="text-center text-sm text-muted-foreground">
        Already have an account?{' '}
        <Link href="/login" className={AUTH_LINK_CLASS}>
          Sign in
        </Link>
      </p>
    </section>
  );
}
