'use client';

import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useToast } from '@/hooks/use-toast';
import { upsertAppSettingAction } from '@/app/actions/admin/settings-actions';
import { getAvailableThemes, DEFAULT_THEME } from '@/config/themes';
import { Loader2, Check, Palette } from 'lucide-react';
import { cn } from '@/lib/utils';

interface ThemeSettingsFormProps {
  initialTheme: string;
}

export function ThemeSettingsForm({ initialTheme }: ThemeSettingsFormProps) {
  const { toast } = useToast();
  const [isLoading, setIsLoading] = useState(false);
  const [selectedTheme, setSelectedTheme] = useState(initialTheme || DEFAULT_THEME);

  const themes = getAvailableThemes();
  const hasChanged = selectedTheme !== initialTheme;

  const handleSave = async () => {
    setIsLoading(true);

    try {
      const result = await upsertAppSettingAction({
        key: 'active_theme',
        value: selectedTheme,
        category: 'theme',
        description: 'The active site-wide theme preset',
      });

      if (!result.success) {
        throw new Error(result.error || 'Failed to update theme');
      }

      toast({
        title: 'Theme Updated',
        description: `Theme changed to "${themes.find((t) => t.name === selectedTheme)?.label}". Reload the page to see changes.`,
      });
    } catch (error: any) {
      console.error('Save theme error:', error);
      toast({
        title: 'Error',
        description: error.message || 'Failed to save theme',
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Palette className="h-5 w-5" />
          Site Theme
        </CardTitle>
        <CardDescription>
          Choose the visual theme for the entire application. Changes apply site-wide after saving
          and take effect on next page load.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid gap-4 md:grid-cols-2">
          {themes.map((theme) => (
            <button
              key={theme.name}
              type="button"
              onClick={() => setSelectedTheme(theme.name)}
              className={cn(
                'relative rounded-xl border-2 p-4 text-left transition-all duration-200',
                selectedTheme === theme.name
                  ? 'border-primary ring-2 ring-primary/20'
                  : 'border-border hover:border-primary/40'
              )}
            >
              {selectedTheme === theme.name && (
                <div className="absolute right-3 top-3">
                  <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary">
                    <Check className="h-4 w-4 text-primary-foreground" />
                  </div>
                </div>
              )}

              <div className="mb-3 flex gap-2">
                <div
                  className="h-8 w-8 rounded-full border border-border/50"
                  style={{ backgroundColor: theme.previewColors.background }}
                  title="Background"
                />
                <div
                  className="h-8 w-8 rounded-full border border-border/50"
                  style={{ backgroundColor: theme.previewColors.primary }}
                  title="Primary"
                />
                <div
                  className="h-8 w-8 rounded-full border border-border/50"
                  style={{ backgroundColor: theme.previewColors.accent }}
                  title="Accent"
                />
              </div>

              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-semibold">{theme.label}</span>
                  {initialTheme === theme.name && (
                    <Badge variant="secondary" className="text-xs">
                      Current
                    </Badge>
                  )}
                </div>
                <p className="text-sm text-muted-foreground">{theme.description}</p>
              </div>
            </button>
          ))}
        </div>

        <div className="pt-2">
          <Button
            onClick={handleSave}
            disabled={isLoading || !hasChanged}
            size="lg"
            className="min-w-[140px]"
          >
            {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {hasChanged ? 'Save Theme' : 'No Changes'}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
