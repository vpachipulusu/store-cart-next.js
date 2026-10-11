import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { db } from '@/lib/db/client';
import { getCurrencySymbol } from '@/config/subscriptions';
import { GeneralSettingsForm } from '@/components/admin/general-settings-form';
import { FeatureFlagsList } from '@/components/admin/feature-flags-list';
import { ThemeSettingsForm } from '@/components/admin/theme-settings-form';
import { DEFAULT_THEME } from '@/config/themes';

async function getSettings() {
  const [generalSettings, featureFlags, emailTemplates, themeSetting] = await Promise.all([
    db.appSettings.findMany({ where: { category: 'general' } }),
    db.featureFlag.findMany({ orderBy: { name: 'asc' } }),
    db.emailTemplate.findMany({ orderBy: { name: 'asc' } }),
    db.appSettings.findUnique({ where: { key: 'active_theme' } }),
  ]);

  // Convert generalSettings to key-value object
  const settingsObject: Record<string, any> = {};
  generalSettings.forEach((setting: { key: string; value: any }) => {
    settingsObject[setting.key] = setting.value;
  });

  const activeTheme = themeSetting?.value
    ? typeof themeSetting.value === 'string'
      ? themeSetting.value
      : String(themeSetting.value)
    : DEFAULT_THEME;

  return {
    generalSettings: settingsObject,
    featureFlags,
    emailTemplates,
    activeTheme,
  };
}

export default async function AdminSettingsPage() {
  const [settings, currencySymbol] = await Promise.all([
    getSettings(),
    getCurrencySymbol(),
  ]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">Manage application settings and configuration</p>
      </div>

      {/* Settings Tabs */}
      <Tabs defaultValue="general" className="space-y-4">
        <TabsList>
          <TabsTrigger value="general">General</TabsTrigger>
          <TabsTrigger value="theme">Theme</TabsTrigger>
          <TabsTrigger value="features">Feature Flags</TabsTrigger>
          <TabsTrigger value="email">Email Templates</TabsTrigger>
          <TabsTrigger value="pricing">Pricing</TabsTrigger>
        </TabsList>

        {/* General Settings */}
        <TabsContent value="general" className="space-y-4">
          <GeneralSettingsForm initialSettings={settings.generalSettings} />
        </TabsContent>

        {/* Theme Settings */}
        <TabsContent value="theme" className="space-y-4">
          <ThemeSettingsForm initialTheme={settings.activeTheme} />
        </TabsContent>

        {/* Feature Flags */}
        <TabsContent value="features" className="space-y-4">
          <FeatureFlagsList flags={settings.featureFlags} />
        </TabsContent>

        {/* Email Templates */}
        <TabsContent value="email" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Email Templates</CardTitle>
              <CardDescription>Manage transactional email templates</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {settings.emailTemplates.length > 0 ? (
                settings.emailTemplates.map((template: any) => (
                  <div key={template.id} className="space-y-2 rounded-lg border p-4">
                    <div className="flex items-center justify-between">
                      <p className="font-medium capitalize">{template.name.replace('-', ' ')}</p>
                      <Button variant="outline" size="sm">
                        Edit
                      </Button>
                    </div>
                    <p className="text-sm text-muted-foreground">Subject: {template.subject}</p>
                  </div>
                ))
              ) : (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  No email templates configured
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Pricing */}
        <TabsContent value="pricing" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Pricing Configuration</CardTitle>
              <CardDescription>Manage subscription plans and pricing</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-4">
                <h3 className="font-semibold">Pro Plan</h3>
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="pro-price">Monthly Price ({currencySymbol})</Label>
                    <Input id="pro-price" type="number" defaultValue="29" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="pro-stripe-id">Stripe Price ID</Label>
                    <Input id="pro-stripe-id" placeholder="price_..." />
                  </div>
                </div>
              </div>

              <div className="space-y-4">
                <h3 className="font-semibold">Enterprise Plan</h3>
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="enterprise-price">Monthly Price ({currencySymbol})</Label>
                    <Input id="enterprise-price" type="number" defaultValue="99" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="enterprise-stripe-id">Stripe Price ID</Label>
                    <Input id="enterprise-stripe-id" placeholder="price_..." />
                  </div>
                </div>
              </div>

              <Button>Save Pricing</Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
