'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { getUserSettingsAction, updateUserSettingsAction } from '@/app/actions/user-actions';
import { Panel } from '@/components/dashboard/overview/panel';
import { ConnectPaymentsPanel } from '@/components/dashboard/settings/connect-payments-panel';
import {
  FormActions,
  FormPageSkeleton,
  LoadFailedPanel,
  PageHeader,
  PanelHint,
} from '@/components/dashboard/settings/form-page';
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Moon, Sun, Globe } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';

const settingsSchema = z.object({
  theme: z.enum(['light', 'dark', 'system']),
  emailNotifications: z.boolean(),
  language: z.string(),
  timezone: z.string(),
});

type SettingsFormValues = z.infer<typeof settingsSchema>;

export default function SettingsPage() {
  const router = useRouter();
  const { toast } = useToast();
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const form = useForm<SettingsFormValues>({
    resolver: zodResolver(settingsSchema),
    defaultValues: {
      theme: 'system',
      emailNotifications: true,
      language: 'en',
      timezone: 'UTC',
    },
  });

  useEffect(() => {
    let cancelled = false;

    async function loadSettings() {
      try {
        const result = await getUserSettingsAction();
        if (cancelled) return;

        if (!result.success || !result.data) {
          setLoadFailed(true);
          toast({
            title: 'Error',
            description: result.error || 'Failed to load settings',
            variant: 'destructive',
          });
          return;
        }

        setLoadFailed(false);
        const settings = result.data.settings;
        form.reset({
          theme: settings.theme as 'light' | 'dark' | 'system',
          emailNotifications: settings.emailNotifications,
          language: settings.language,
          timezone: settings.timezone,
        });
      } catch (error) {
        if (cancelled) return;
        console.error('Load settings error:', error);
        setLoadFailed(true);
        toast({
          title: 'Error',
          description: 'An unexpected error occurred',
          variant: 'destructive',
        });
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    loadSettings();
    return () => {
      cancelled = true;
    };
  }, [form, toast, attempt]);

  function retryLoad() {
    setIsLoading(true);
    setAttempt((count) => count + 1);
  }

  async function onSubmit(data: SettingsFormValues) {
    try {
      setIsSaving(true);

      const result = await updateUserSettingsAction(data);

      if (!result.success) {
        toast({
          title: 'Error',
          description: result.error || 'Failed to update settings',
          variant: 'destructive',
        });
        return;
      }

      form.reset(data);
      toast({
        title: 'Success',
        description: 'Settings updated successfully',
      });

      router.refresh();
    } catch (error) {
      console.error('Update settings error:', error);
      toast({
        title: 'Error',
        description: 'An unexpected error occurred',
        variant: 'destructive',
      });
    } finally {
      setIsSaving(false);
    }
  }

  if (isLoading) {
    return <FormPageSkeleton label="Loading settings" panels={3} />;
  }

  if (loadFailed) {
    return (
      <div className="space-y-6">
        <PageHeader title="Settings" description="Manage your account preferences and settings" />
        <LoadFailedPanel message="We could not load your settings." onRetry={retryLoad} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" description="Manage your account preferences and settings" />

      <Form {...form}>
        <form noValidate onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
          <Panel title="Appearance" titleId="appearance-title">
            <PanelHint>Customize how the app looks and feels</PanelHint>
            <FormField
              control={form.control}
              name="theme"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Theme</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Select a theme" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="light">
                        <div className="flex items-center gap-2">
                          <Sun aria-hidden="true" className="h-4 w-4" />
                          Light
                        </div>
                      </SelectItem>
                      <SelectItem value="dark">
                        <div className="flex items-center gap-2">
                          <Moon aria-hidden="true" className="h-4 w-4" />
                          Dark
                        </div>
                      </SelectItem>
                      <SelectItem value="system">
                        <div className="flex items-center gap-2">
                          <Globe aria-hidden="true" className="h-4 w-4" />
                          System
                        </div>
                      </SelectItem>
                    </SelectContent>
                  </Select>
                  <FormDescription>Choose your preferred color theme</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          </Panel>

          <Panel title="Notifications" titleId="notifications-title">
            <PanelHint>Configure how you receive notifications</PanelHint>
            <FormField
              control={form.control}
              name="emailNotifications"
              render={({ field }) => (
                <FormItem className="flex flex-row items-center justify-between gap-4 rounded-lg border p-4">
                  <div className="min-w-0 space-y-0.5">
                    <FormLabel className="text-base">Email Notifications</FormLabel>
                    <FormDescription>
                      Receive email notifications about your account activity
                    </FormDescription>
                  </div>
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={field.onChange}
                      className="relative before:absolute before:-inset-2.5 before:content-['']"
                    />
                  </FormControl>
                </FormItem>
              )}
            />
          </Panel>

          <Panel title="Regional Settings" titleId="regional-title">
            <PanelHint>Set your language and timezone preferences</PanelHint>
            <div className="space-y-6">
              <FormField
                control={form.control}
                name="language"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Language</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Select a language" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="en">English</SelectItem>
                        <SelectItem value="es">Español</SelectItem>
                        <SelectItem value="fr">Français</SelectItem>
                        <SelectItem value="de">Deutsch</SelectItem>
                        <SelectItem value="ja">日本語</SelectItem>
                        <SelectItem value="zh">中文</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormDescription>Choose your preferred language</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="timezone"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Timezone</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Select a timezone" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="UTC">UTC</SelectItem>
                        <SelectItem value="America/New_York">Eastern Time (ET)</SelectItem>
                        <SelectItem value="America/Chicago">Central Time (CT)</SelectItem>
                        <SelectItem value="America/Denver">Mountain Time (MT)</SelectItem>
                        <SelectItem value="America/Los_Angeles">Pacific Time (PT)</SelectItem>
                        <SelectItem value="Europe/London">London (GMT)</SelectItem>
                        <SelectItem value="Europe/Paris">Paris (CET)</SelectItem>
                        <SelectItem value="Asia/Tokyo">Tokyo (JST)</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      Select your timezone for accurate time display
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
          </Panel>

          <FormActions
            isSaving={isSaving}
            saveLabel="Save Settings"
            secondaryLabel="Reset"
            onSecondary={() => form.reset()}
          />
        </form>
      </Form>

      <ConnectPaymentsPanel />
    </div>
  );
}
