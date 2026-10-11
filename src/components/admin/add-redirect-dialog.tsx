'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { useToast } from '@/hooks/use-toast';
import { createURLRedirectAction } from '@/app/actions/admin/seo-actions';
import { Loader2, Plus } from 'lucide-react';
import { useRouter } from 'next/navigation';

export function AddRedirectDialog() {
  const { toast } = useToast();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const [formData, setFormData] = useState({
    fromPath: '',
    toPath: '',
    statusCode: 301,
    enabled: true,
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      const result = await createURLRedirectAction(formData);

      if (!result.success) {
        toast({
          title: 'Error',
          description: result.error || 'Failed to create redirect',
          variant: 'destructive',
        });
        return;
      }

      toast({
        title: 'Success',
        description: 'URL redirect created successfully',
      });

      setOpen(false);
      setFormData({
        fromPath: '',
        toPath: '',
        statusCode: 301,
        enabled: true,
      });

      router.refresh();
    } catch (error: any) {
      toast({
        title: 'Error',
        description: error.message || 'Failed to create redirect',
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="mr-2 h-4 w-4" />
          Add Redirect
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Add URL Redirect</DialogTitle>
            <DialogDescription>
              Redirect old URLs to new locations. Use 301 for permanent, 302 for temporary.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="fromPath" className="text-sm font-semibold">
                From Path <span className="text-destructive">*</span>
              </Label>
              <Input
                id="fromPath"
                placeholder="/old-page"
                value={formData.fromPath}
                onChange={(e) => setFormData({ ...formData, fromPath: e.target.value })}
                required
              />
              <p className="text-xs text-muted-foreground">
                The old URL path that should redirect (e.g., /old-page)
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="toPath" className="text-sm font-semibold">
                To Path <span className="text-destructive">*</span>
              </Label>
              <Input
                id="toPath"
                placeholder="/new-page"
                value={formData.toPath}
                onChange={(e) => setFormData({ ...formData, toPath: e.target.value })}
                required
              />
              <p className="text-xs text-muted-foreground">
                The new URL path to redirect to (e.g., /new-page or https://example.com)
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="statusCode" className="text-sm font-semibold">
                Redirect Type
              </Label>
              <Select
                value={formData.statusCode.toString()}
                onValueChange={(value) => setFormData({ ...formData, statusCode: parseInt(value) })}
              >
                <SelectTrigger id="statusCode">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="301">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold">301</span>
                      <span className="text-muted-foreground">·</span>
                      <span>Permanent Redirect</span>
                    </div>
                  </SelectItem>
                  <SelectItem value="302">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold">302</span>
                      <span className="text-muted-foreground">·</span>
                      <span>Temporary Redirect</span>
                    </div>
                  </SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                301: Permanent (recommended for SEO). 302: Temporary
              </p>
            </div>

            <div className="flex items-center justify-between rounded-lg border p-4">
              <div className="space-y-0.5">
                <Label htmlFor="enabled" className="text-sm font-semibold">
                  Enable Redirect
                </Label>
                <p className="text-xs text-muted-foreground">Activate this redirect immediately</p>
              </div>
              <Switch
                id="enabled"
                checked={formData.enabled}
                onCheckedChange={(checked) => setFormData({ ...formData, enabled: checked })}
              />
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={isLoading}>
              {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Create Redirect
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
