import Link from 'next/link';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { SearchX, Home } from 'lucide-react';

/**
 * Not Found Component
 *
 * Custom 404 page for handling missing routes
 * Provides navigation options to help users find what they need
 */
export default function NotFound() {
  return (
    <div className="container flex min-h-screen items-center justify-center py-10">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-theme-accent/[0.08]">
            <SearchX className="h-8 w-8 text-theme-accent" />
          </div>
          <CardTitle className="text-2xl font-semibold">Page Not Found</CardTitle>
          <CardDescription>
            The page you're looking for doesn't exist or has been moved.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-lg bg-muted/50 p-4 text-center">
            <p className="text-7xl font-bold text-theme-accent/30">404</p>
          </div>
          <div className="text-center text-sm text-muted-foreground">
            <p>If you believe this is a mistake, please contact support or try navigating back.</p>
          </div>
        </CardContent>
        <CardFooter className="flex justify-center">
          <Button asChild size="lg">
            <Link href="/">
              <Home className="mr-2 h-4 w-4" />
              Go Home
            </Link>
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
