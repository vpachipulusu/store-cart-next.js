'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { getUserProfileAction, updateUserProfileAction } from '@/app/actions/user-actions';
import { Panel } from '@/components/dashboard/overview/panel';
import { AvatarField } from '@/components/dashboard/profile/avatar-field';
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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/hooks/use-toast';

const profileSchema = z.object({
  displayName: z.string().min(2, 'Display name must be at least 2 characters').optional(),
  bio: z.string().max(500, 'Bio must not exceed 500 characters').optional(),
  location: z.string().optional(),
  website: z.string().url('Must be a valid URL').optional().or(z.literal('')),
  phoneNumber: z.string().optional(),
});

type ProfileFormValues = z.infer<typeof profileSchema>;

interface ProfileUser {
  email?: string;
  displayName?: string;
}

export default function ProfilePage() {
  const router = useRouter();
  const { toast } = useToast();
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [userData, setUserData] = useState<ProfileUser | null>(null);
  const [avatarUrl, setAvatarUrl] = useState<string>('');
  const [loadFailed, setLoadFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const form = useForm<ProfileFormValues>({
    resolver: zodResolver(profileSchema),
    defaultValues: {
      displayName: '',
      bio: '',
      location: '',
      website: '',
      phoneNumber: '',
    },
  });

  useEffect(() => {
    let cancelled = false;

    async function loadProfile() {
      try {
        const result = await getUserProfileAction();
        if (cancelled) return;

        if (!result.success || !result.data) {
          setLoadFailed(true);
          toast({
            title: 'Error',
            description: result.error || 'Failed to load profile',
            variant: 'destructive',
          });
          return;
        }

        setLoadFailed(false);
        const user = result.data.user;
        setUserData(user);
        setAvatarUrl(user.avatarUrl || '');

        form.reset({
          displayName: user.displayName || '',
          bio: user.bio || '',
          location: user.location || '',
          website: user.website || '',
          phoneNumber: user.phoneNumber || '',
        });
      } catch (error) {
        if (cancelled) return;
        console.error('Load profile error:', error);
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

    loadProfile();
    return () => {
      cancelled = true;
    };
  }, [form, toast, attempt]);

  function retryLoad() {
    setIsLoading(true);
    setAttempt((count) => count + 1);
  }

  async function onSubmit(data: ProfileFormValues) {
    try {
      setIsSaving(true);

      const result = await updateUserProfileAction(data);

      if (!result.success) {
        toast({
          title: 'Error',
          description: result.error || 'Failed to update profile',
          variant: 'destructive',
        });
        return;
      }

      form.reset(data);
      toast({
        title: 'Success',
        description: 'Profile updated successfully',
      });

      router.refresh();
    } catch (error) {
      console.error('Update profile error:', error);
      toast({
        title: 'Error',
        description: 'An unexpected error occurred',
        variant: 'destructive',
      });
    } finally {
      setIsSaving(false);
    }
  }

  function handleAvatarSelect() {
    // In a real app, upload to a storage service (e.g., Firebase Storage, AWS S3)
    // For now, we'll use a placeholder
    toast({
      title: 'Info',
      description: 'Avatar upload would happen here. Integrate with your storage service.',
    });
  }

  if (isLoading) {
    return <FormPageSkeleton label="Loading profile" panels={2} />;
  }

  if (loadFailed) {
    return (
      <div className="space-y-6">
        <PageHeader title="Profile" description="Manage your public profile information" />
        <LoadFailedPanel message="We could not load your profile." onRetry={retryLoad} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Profile" description="Manage your public profile information" />

      <Panel title="Profile Picture" titleId="profile-picture-title">
        <PanelHint>Upload a photo to personalize your account</PanelHint>
        <AvatarField
          avatarUrl={avatarUrl}
          name={userData?.displayName || 'User'}
          initial={userData?.email?.charAt(0).toUpperCase() ?? ''}
          onSelect={handleAvatarSelect}
        />
      </Panel>

      <Panel title="Personal Information" titleId="personal-information-title">
        <PanelHint>Update your personal details and public profile</PanelHint>
        <Form {...form}>
          <form noValidate onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="profile-email">Email</Label>
              <Input
                id="profile-email"
                value={userData?.email || ''}
                disabled
                aria-describedby="profile-email-hint"
                className="bg-muted"
              />
              <p id="profile-email-hint" className="text-[0.8rem] text-muted-foreground">
                Your email address cannot be changed
              </p>
            </div>

            <FormField
              control={form.control}
              name="displayName"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Display Name</FormLabel>
                  <FormControl>
                    <Input placeholder="Your name" {...field} />
                  </FormControl>
                  <FormDescription>
                    This is how your name will be displayed across the platform
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="bio"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Bio</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="Tell us about yourself"
                      className="min-h-[100px]"
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Brief description for your profile (max 500 characters)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="location"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Location</FormLabel>
                  <FormControl>
                    <Input placeholder="City, Country" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="website"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Website</FormLabel>
                  <FormControl>
                    <Input type="url" placeholder="https://yourwebsite.com" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="phoneNumber"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Phone Number</FormLabel>
                  <FormControl>
                    <Input type="tel" placeholder="+1 (555) 000-0000" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormActions
              isSaving={isSaving}
              saveLabel="Save Changes"
              secondaryLabel="Cancel"
              onSecondary={() => form.reset()}
            />
          </form>
        </Form>
      </Panel>
    </div>
  );
}
