import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

type FeatureUnavailableProps = {
  title: string;
  description: string;
};

/**
 * State for admin pages that have no backend API yet (KAN-184). The page is switched off rather than left
 * reading the database directly; it returns when its API exists (KAN-114).
 */
export function FeatureUnavailable({ title, description }: FeatureUnavailableProps) {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
        <p className="text-muted-foreground">{description}</p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Not available yet</CardTitle>
          <CardDescription>
            This page is switched off until its backend service is ready. Nothing is lost: it will
            return in a later release.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" asChild>
            <Link href="/admin/users">Go to Users</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
