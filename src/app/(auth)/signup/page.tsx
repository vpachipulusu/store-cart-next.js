import Link from 'next/link';
import { SignupForm } from '@/components/auth/signup-form';
import { OAuthButtons } from '@/components/auth/oauth-buttons';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';

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
    <Card>
      <CardHeader className="space-y-1">
        <div className="mb-3 h-px w-12 bg-gradient-to-r from-theme-accent to-transparent" />
        <CardTitle className="text-2xl">Create an account</CardTitle>
        <CardDescription>Enter your information to get started</CardDescription>
        {selectedPlan && (
          <div className="pt-2">
            <Badge variant="secondary" className="capitalize border-theme-accent/20 bg-theme-accent/10 text-theme-accent-dark dark:text-theme-accent-light">
              Selected Plan: {selectedPlan}
            </Badge>
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <OAuthButtons />

        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <Separator />
          </div>
          <div className="relative flex justify-center text-xs uppercase">
            <span className="bg-card px-2 text-muted-foreground">Or continue with email</span>
          </div>
        </div>

        <SignupForm selectedPlan={selectedPlan} />
      </CardContent>
      <CardFooter>
        <p className="w-full text-center text-sm text-muted-foreground">
          Already have an account?{' '}
          <Link href="/login" className="font-medium text-primary hover:underline">
            Sign in
          </Link>
        </p>
      </CardFooter>
    </Card>
  );
}
