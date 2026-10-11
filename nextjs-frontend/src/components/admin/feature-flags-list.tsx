'use client';

import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useToast } from '@/hooks/use-toast';
import { toggleFeatureFlagAction } from '@/app/actions/admin/settings-actions';

interface FeatureFlagsListProps {
  flags: Array<{
    id: string;
    name: string;
    enabled: boolean;
    description: string | null;
  }>;
}

export function FeatureFlagsList({ flags: initialFlags }: FeatureFlagsListProps) {
  const { toast } = useToast();
  const [flags, setFlags] = useState(initialFlags);
  const [updating, setUpdating] = useState<string | null>(null);

  const handleToggle = async (flagName: string, currentEnabled: boolean) => {
    setUpdating(flagName);

    try {
      // Optimistically update UI
      setFlags(
        flags.map((flag) => (flag.name === flagName ? { ...flag, enabled: !currentEnabled } : flag))
      );

      // Call server action to toggle feature flag
      const result = await toggleFeatureFlagAction(flagName);

      if (!result.success) {
        // Revert on error
        setFlags(
          flags.map((flag) =>
            flag.name === flagName ? { ...flag, enabled: currentEnabled } : flag
          )
        );

        toast({
          title: 'Error',
          description: result.error || 'Failed to update feature flag',
          variant: 'destructive',
        });
      } else {
        toast({
          title: 'Success',
          description: 'Feature flag updated successfully',
        });
      }
    } catch (error: any) {
      // Revert on error
      setFlags(
        flags.map((flag) => (flag.name === flagName ? { ...flag, enabled: currentEnabled } : flag))
      );

      toast({
        title: 'Error',
        description: error.message || 'Failed to update feature flag',
        variant: 'destructive',
      });
    } finally {
      setUpdating(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Feature Flags</CardTitle>
        <CardDescription>Enable or disable features across the platform</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {flags.length > 0 ? (
          flags.map((flag) => (
            <div key={flag.id} className="flex items-center justify-between rounded-lg border p-4">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <p className="font-medium">{flag.name}</p>
                  {flag.enabled && <Badge variant="default">Enabled</Badge>}
                </div>
                <p className="text-sm text-muted-foreground">
                  {flag.description || 'No description'}
                </p>
              </div>
              <Switch
                checked={flag.enabled}
                onCheckedChange={() => handleToggle(flag.name, flag.enabled)}
                disabled={updating === flag.name}
              />
            </div>
          ))
        ) : (
          <p className="py-4 text-center text-sm text-muted-foreground">
            No feature flags configured
          </p>
        )}
      </CardContent>
    </Card>
  );
}
