import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/components/auth/login-form', () => ({
  LoginForm: () => <form data-testid="login-form" />,
}));
vi.mock('@/components/auth/signup-form', () => ({
  SignupForm: () => <form data-testid="signup-form" />,
}));
vi.mock('@/components/auth/password-reset-form', () => ({
  PasswordResetForm: () => <form data-testid="reset-form" />,
}));
vi.mock('@/components/auth/oauth-buttons', () => ({ OAuthButtons: () => <div /> }));
vi.mock('@/lib/firebase/client', () => ({ auth: {} }));
vi.mock('firebase/auth', () => ({ onAuthStateChanged: vi.fn(() => () => {}) }));
vi.mock('@/lib/firebase/auth-helpers', () => ({ resendVerificationEmail: vi.fn() }));
vi.mock('@/app/actions/auth-actions', () => ({ refreshSessionAction: vi.fn() }));

import AuthLayout from '@/app/(auth)/layout';
import LoginPage from '@/app/(auth)/login/page';
import SignupPage from '@/app/(auth)/signup/page';
import ResetPasswordPage from '@/app/(auth)/reset-password/page';
import VerifyEmailPage from '@/app/(auth)/verify-email/page';

/** KAN-228: auth shell with an inverse brand panel from 760px, one h1 per page, tokens only. */

const RAW_COLOURS =
  /#[0-9a-f]{3,6}\b|rgb\(|text-white|bg-white|bg-gradient|from-theme|theme-accent/i;

describe('auth layout', () => {
  it('has one main landmark with the skip target and a skip link', () => {
    const { container } = render(
      <AuthLayout>
        <p>child</p>
      </AuthLayout>
    );

    const mains = container.querySelectorAll('main');
    expect(mains).toHaveLength(1);
    expect(mains[0]).toHaveAttribute('id', 'main-content');
    expect(mains[0]).toHaveAttribute('tabindex', '-1');
    expect(within(mains[0] as HTMLElement).getByText('child')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /skip to main content/i })).toHaveAttribute(
      'href',
      '#main-content'
    );
  });

  it('shows the inverse brand panel only from 760px and keeps the form on phones', () => {
    render(
      <AuthLayout>
        <p>child</p>
      </AuthLayout>
    );

    const panel = screen.getByRole('complementary', { hidden: true });
    expect(panel.className).toMatch(/\bhidden\b/);
    expect(panel.className).toMatch(/min-\[760px\]:flex/);
    expect(panel.className).toMatch(/bg-feature/);
    expect(panel.className).toMatch(/on-inverse/);
    // Panel adds no heading, so each page keeps exactly one h1.
    expect(within(panel).queryAllByRole('heading', { hidden: true })).toHaveLength(0);
  });

  it('shows a small brand link on phones only, linking home', () => {
    const { container } = render(
      <AuthLayout>
        <p>child</p>
      </AuthLayout>
    );

    const phoneBrand = container.querySelector('main a[href="/"]') as HTMLElement;
    expect(phoneBrand).toHaveTextContent('StoreCart');
    expect(phoneBrand.className).toMatch(/min-\[760px\]:hidden/);
    expect(phoneBrand.className).toMatch(/min-h-11/);
  });

  it('uses tokens only and no entrance animation that ignores reduced motion', () => {
    const { container } = render(
      <AuthLayout>
        <p>child</p>
      </AuthLayout>
    );

    expect(container.innerHTML).not.toMatch(RAW_COLOURS);
    expect(container.innerHTML).not.toMatch(/animate-/);
  });
});

describe('auth pages', () => {
  const pages: Array<[string, () => Promise<React.ReactElement> | React.ReactElement, RegExp]> = [
    ['login', () => <LoginPage />, /welcome back/i],
    [
      'signup',
      async () => await SignupPage({ searchParams: Promise.resolve({}) }),
      /create an account/i,
    ],
    ['reset-password', () => <ResetPasswordPage />, /reset your password/i],
    ['verify-email', () => <VerifyEmailPage />, /verify your email/i],
  ];

  it.each(pages)('%s renders exactly one h1 and tokens only', async (_name, build, title) => {
    const { container } = render(await build());

    const h1s = screen.getAllByRole('heading', { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent(title);
    expect(container.querySelector('main')).toBeNull();
    expect(container.innerHTML).not.toMatch(RAW_COLOURS);
  });

  it('login keeps its form and a sign-up cross link with a 44px target', () => {
    render(<LoginPage />);
    const signUp = screen.getByRole('link', { name: /sign up/i });
    expect(signUp).toHaveAttribute('href', '/signup');
    expect(signUp.className).toMatch(/min-h-11/);
    expect(screen.getByTestId('login-form')).toBeInTheDocument();
  });

  it('signup keeps its form and a sign-in cross link with a 44px target', async () => {
    render(await SignupPage({ searchParams: Promise.resolve({}) }));
    const signIn = screen.getByRole('link', { name: /sign in/i });
    expect(signIn).toHaveAttribute('href', '/login');
    expect(signIn.className).toMatch(/min-h-11/);
    expect(screen.getByTestId('signup-form')).toBeInTheDocument();
  });

  it('signup shows the selected plan as a pill', async () => {
    render(await SignupPage({ searchParams: Promise.resolve({ plan: 'pro' }) }));

    const pill = screen.getByText(/selected plan: pro/i);
    expect(pill.className).toMatch(/rounded-full/);
    expect(pill.className).not.toMatch(/theme-accent/);
    expect(screen.getByTestId('signup-form')).toBeInTheDocument();
  });

  it('signup omits the pill without a plan', async () => {
    render(await SignupPage({ searchParams: Promise.resolve({}) }));

    expect(screen.queryByText(/selected plan/i)).toBeNull();
  });

  it('verify-email is restyled with an info icon tile and accent-free tokens', () => {
    const { container } = render(<VerifyEmailPage />);

    expect(container.innerHTML).not.toMatch(/theme-accent/);
    expect(container.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    expect(screen.getByRole('button', { name: /resend verification email/i }).className).toMatch(
      /h-1[12]|min-h-11/
    );
  });

  it('reset-password links back to sign in with a 44px target', () => {
    render(<ResetPasswordPage />);

    const link = screen.getByRole('link', { name: /sign in/i });
    expect(link).toHaveAttribute('href', '/login');
    expect(link.className).toMatch(/min-h-11/);
  });
});
