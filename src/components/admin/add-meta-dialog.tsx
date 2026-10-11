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
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { useToast } from '@/hooks/use-toast';
import { upsertSEOMetaAction } from '@/app/actions/admin/seo-actions';
import { Loader2, Plus } from 'lucide-react';
import { useRouter } from 'next/navigation';

export function AddMetaDialog() {
  const { toast } = useToast();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const [formData, setFormData] = useState({
    page: '',
    title: '',
    description: '',
    keywords: '',
    ogTitle: '',
    ogDescription: '',
    ogImage: '',
    canonical: '',
    noindex: false,
    nofollow: false,
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      const result = await upsertSEOMetaAction(formData);

      if (!result.success) {
        toast({
          title: 'Error',
          description: result.error || 'Failed to add SEO meta tag',
          variant: 'destructive',
        });
        return;
      }

      toast({
        title: 'Success',
        description: 'SEO meta tag added successfully',
      });

      setOpen(false);
      setFormData({
        page: '',
        title: '',
        description: '',
        keywords: '',
        ogTitle: '',
        ogDescription: '',
        ogImage: '',
        canonical: '',
        noindex: false,
        nofollow: false,
      });

      router.refresh();
    } catch (error: any) {
      toast({
        title: 'Error',
        description: error.message || 'Failed to add SEO meta tag',
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
          Add Page
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Add SEO Meta Tags</DialogTitle>
            <DialogDescription>
              Configure meta tags for a new page. These will improve search engine visibility.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="page" className="text-sm font-semibold">
                Page Path <span className="text-destructive">*</span>
              </Label>
              <Input
                id="page"
                placeholder="/pricing"
                value={formData.page}
                onChange={(e) => setFormData({ ...formData, page: e.target.value })}
                required
              />
              <p className="text-xs text-muted-foreground">
                Use "/" for homepage, or paths like "/about", "/pricing"
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="title" className="text-sm font-semibold">
                Page Title <span className="text-destructive">*</span>
              </Label>
              <Input
                id="title"
                placeholder="Amazing Product - Your Company"
                value={formData.title}
                onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                required
                maxLength={60}
              />
              <p className="text-xs text-muted-foreground">
                {formData.title.length}/60 characters (recommended: 50-60)
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="description" className="text-sm font-semibold">
                Meta Description <span className="text-destructive">*</span>
              </Label>
              <Textarea
                id="description"
                placeholder="Describe your page in a compelling way..."
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                required
                maxLength={160}
                rows={3}
              />
              <p className="text-xs text-muted-foreground">
                {formData.description.length}/160 characters (recommended: 150-160)
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="keywords" className="text-sm font-semibold">
                Keywords (Optional)
              </Label>
              <Input
                id="keywords"
                placeholder="saas, pricing, subscription"
                value={formData.keywords}
                onChange={(e) => setFormData({ ...formData, keywords: e.target.value })}
              />
              <p className="text-xs text-muted-foreground">Comma-separated keywords</p>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="ogTitle" className="text-sm font-semibold">
                  Open Graph Title
                </Label>
                <Input
                  id="ogTitle"
                  placeholder={formData.title || 'For social media sharing'}
                  value={formData.ogTitle}
                  onChange={(e) => setFormData({ ...formData, ogTitle: e.target.value })}
                  maxLength={60}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="ogImage" className="text-sm font-semibold">
                  Open Graph Image URL
                </Label>
                <Input
                  id="ogImage"
                  type="url"
                  placeholder="https://yoursite.com/og-image.jpg"
                  value={formData.ogImage}
                  onChange={(e) => setFormData({ ...formData, ogImage: e.target.value })}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="ogDescription" className="text-sm font-semibold">
                Open Graph Description
              </Label>
              <Textarea
                id="ogDescription"
                placeholder={formData.description || 'Description for social shares'}
                value={formData.ogDescription}
                onChange={(e) => setFormData({ ...formData, ogDescription: e.target.value })}
                maxLength={160}
                rows={2}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="canonical" className="text-sm font-semibold">
                Canonical URL (Optional)
              </Label>
              <Input
                id="canonical"
                type="url"
                placeholder="https://yoursite.com/canonical-page"
                value={formData.canonical}
                onChange={(e) => setFormData({ ...formData, canonical: e.target.value })}
              />
              <p className="text-xs text-muted-foreground">
                Specify if this page is a duplicate of another URL
              </p>
            </div>

            <div className="flex items-center justify-between rounded-lg border p-4">
              <div className="space-y-0.5">
                <Label htmlFor="noindex" className="text-sm font-semibold">
                  No Index
                </Label>
                <p className="text-xs text-muted-foreground">
                  Prevent search engines from indexing this page
                </p>
              </div>
              <Switch
                id="noindex"
                checked={formData.noindex}
                onCheckedChange={(checked) => setFormData({ ...formData, noindex: checked })}
              />
            </div>

            <div className="flex items-center justify-between rounded-lg border p-4">
              <div className="space-y-0.5">
                <Label htmlFor="nofollow" className="text-sm font-semibold">
                  No Follow
                </Label>
                <p className="text-xs text-muted-foreground">
                  Prevent search engines from following links on this page
                </p>
              </div>
              <Switch
                id="nofollow"
                checked={formData.nofollow}
                onCheckedChange={(checked) => setFormData({ ...formData, nofollow: checked })}
              />
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={isLoading}>
              {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Add Page
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
