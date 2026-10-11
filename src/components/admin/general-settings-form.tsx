'use client';

import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { upsertAppSettingAction } from '@/app/actions/admin/settings-actions';
import { useToast } from '@/hooks/use-toast';
import { Loader2, DollarSign, Globe, Type } from 'lucide-react';
import { CURRENCIES } from '@/config/subscriptions';
import { getFontOptions } from '@/config/fonts';

interface GeneralSettingsFormProps {
  initialSettings: Record<string, any>;
}

const LANGUAGES = [
  { code: 'en', name: 'English' },
  { code: 'es', name: 'Spanish' },
  { code: 'fr', name: 'French' },
  { code: 'de', name: 'German' },
  { code: 'it', name: 'Italian' },
  { code: 'pt', name: 'Portuguese' },
  { code: 'ja', name: 'Japanese' },
  { code: 'zh', name: 'Chinese' },
  { code: 'ko', name: 'Korean' },
  { code: 'ar', name: 'Arabic' },
  { code: 'hi', name: 'Hindi' },
];

export function GeneralSettingsForm({ initialSettings }: GeneralSettingsFormProps) {
  const { toast } = useToast();
  const [isLoading, setIsLoading] = useState(false);
  const [appName, setAppName] = useState(initialSettings.app_name || 'SaaS Boilerplate');
  const [supportEmail, setSupportEmail] = useState(initialSettings.support_email || '');
  const [defaultTimezone, setDefaultTimezone] = useState(initialSettings.default_timezone || 'UTC');
  const [currency, setCurrency] = useState(initialSettings.currency || 'USD');
  const [language, setLanguage] = useState(initialSettings.language || 'en');
  const [appFont, setAppFont] = useState(initialSettings.app_font || 'inter');

  const fontOptions = getFontOptions();

  const handleSave = async () => {
    setIsLoading(true);

    try {
      // Update all settings
      const updates = [
        {
          key: 'app_name',
          value: appName,
          category: 'general',
          description: 'Application name',
        },
        {
          key: 'support_email',
          value: supportEmail,
          category: 'general',
          description: 'Support contact email',
        },
        {
          key: 'default_timezone',
          value: defaultTimezone,
          category: 'general',
          description: 'Default timezone for the application',
        },
        {
          key: 'currency',
          value: currency,
          category: 'general',
          description: 'Default currency for pricing and billing',
        },
        {
          key: 'language',
          value: language,
          category: 'general',
          description: 'Default language for the application',
        },
        {
          key: 'app_font',
          value: appFont,
          category: 'general',
          description: 'Application font family',
        },
      ];

      for (const update of updates) {
        const result = await upsertAppSettingAction(update);
        if (!result.success) {
          throw new Error(result.error || 'Failed to update setting');
        }
      }

      toast({
        title: 'Success',
        description: 'Settings updated successfully',
      });
    } catch (error: any) {
      console.error('Save settings error:', error);
      toast({
        title: 'Error',
        description: error.message || 'Failed to save settings',
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>General Settings</CardTitle>
        <CardDescription>Configure basic application settings</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-2.5">
          <Label htmlFor="app-name" className="text-sm font-semibold">
            Application Name
          </Label>
          <Input
            id="app-name"
            placeholder="SaaS Boilerplate"
            value={appName}
            onChange={(e) => setAppName(e.target.value)}
          />
        </div>

        <div className="space-y-2.5">
          <Label htmlFor="support-email" className="text-sm font-semibold">
            Support Email
          </Label>
          <Input
            id="support-email"
            type="email"
            placeholder="support@example.com"
            value={supportEmail}
            onChange={(e) => setSupportEmail(e.target.value)}
          />
        </div>

        <div className="space-y-2.5">
          <Label htmlFor="timezone" className="text-sm font-semibold">
            Default Timezone
          </Label>
          <Input
            id="timezone"
            value={defaultTimezone}
            onChange={(e) => setDefaultTimezone(e.target.value)}
            placeholder="UTC"
          />
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          <div className="space-y-2.5">
            <Label htmlFor="currency" className="flex items-center gap-2 text-sm font-semibold">
              <DollarSign className="h-4 w-4 text-primary" />
              Default Currency
            </Label>
            <Select value={currency} onValueChange={setCurrency}>
              <SelectTrigger id="currency">
                <SelectValue placeholder="Select currency">
                  {currency && (
                    <div className="flex items-center gap-2.5">
                      <span className="text-lg leading-none">
                        {CURRENCIES.find((c) => c.code === currency)?.symbol}
                      </span>
                      <span className="font-semibold">
                        {CURRENCIES.find((c) => c.code === currency)?.code}
                      </span>
                      <span className="text-muted-foreground">·</span>
                      <span className="text-muted-foreground">
                        {CURRENCIES.find((c) => c.code === currency)?.name}
                      </span>
                    </div>
                  )}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {CURRENCIES.map((curr) => (
                  <SelectItem key={curr.code} value={curr.code}>
                    <div className="flex items-center gap-2.5">
                      <span className="text-base leading-none">{curr.symbol}</span>
                      <span className="min-w-[3rem] font-semibold">{curr.code}</span>
                      <span className="text-muted-foreground">·</span>
                      <span className="text-muted-foreground">{curr.name}</span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs leading-relaxed text-muted-foreground">
              Currency used for pricing and billing throughout the app
            </p>
          </div>

          <div className="space-y-2.5">
            <Label htmlFor="language" className="flex items-center gap-2 text-sm font-semibold">
              <Globe className="h-4 w-4 text-primary" />
              Default Language
            </Label>
            <Select value={language} onValueChange={setLanguage}>
              <SelectTrigger id="language">
                <SelectValue placeholder="Select language">
                  {language && (
                    <div className="flex items-center gap-2">
                      <span className="font-medium">
                        {LANGUAGES.find((l) => l.code === language)?.name}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        ({language.toUpperCase()})
                      </span>
                    </div>
                  )}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {LANGUAGES.map((lang) => (
                  <SelectItem key={lang.code} value={lang.code}>
                    <div className="flex items-center gap-2.5">
                      <span className="min-w-[6rem] font-medium">{lang.name}</span>
                      <span className="text-xs uppercase text-muted-foreground">({lang.code})</span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs leading-relaxed text-muted-foreground">
              Default language for the application interface
            </p>
          </div>
        </div>

        <div className="space-y-2.5">
          <Label htmlFor="app-font" className="flex items-center gap-2 text-sm font-semibold">
            <Type className="h-4 w-4 text-primary" />
            Application Font
          </Label>
          <Select value={appFont} onValueChange={setAppFont}>
            <SelectTrigger id="app-font">
              <SelectValue placeholder="Select font">
                {appFont && (
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">
                      {fontOptions.find((f) => f.id === appFont)?.name}
                    </span>
                    <span className="text-muted-foreground">·</span>
                    <span className="text-sm text-muted-foreground">
                      {fontOptions.find((f) => f.id === appFont)?.description}
                    </span>
                  </div>
                )}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {fontOptions.map((font) => (
                <SelectItem key={font.id} value={font.id}>
                  <div className="flex flex-col gap-0.5 py-1">
                    <div className="font-semibold">{font.name}</div>
                    <div className="text-xs text-muted-foreground">{font.description}</div>
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs leading-relaxed text-muted-foreground">
            Choose a font that will be used across the entire application. Select a readable option
            that fits your brand.
          </p>
        </div>

        <div className="pt-2">
          <Button onClick={handleSave} disabled={isLoading} size="lg" className="min-w-[140px]">
            {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Save Changes
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
