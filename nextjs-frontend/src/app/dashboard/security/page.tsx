'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  changePasswordAction,
  deleteAccountAction,
  disableTwoFactorAction,
  getLoginHistoryAction,
  getTwoFactorStatusAction,
} from '@/app/actions/user-actions';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Key, Loader2, Clock, ShieldCheck, Trash2 } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import { ReauthDialog } from '@/components/auth/reauth-dialog';
import { reauthenticate, restoreSessionWithNewPassword } from '@/lib/firebase/reauth';
import { auth } from '@/lib/firebase/client';
import { signOut } from 'firebase/auth';

export default function SecurityPage() {
  const { toast } = useToast();
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(true);
  const [loginHistory, setLoginHistory] = useState<any[]>([]);
  // null until the status loads, or when it could not be read (nothing is claimed in that case).
  const [twoFactorEnabled, setTwoFactorEnabled] = useState<boolean | null>(null);
  const [showChangePassword, setShowChangePassword] = useState(false);
  const [isChangingPassword, setIsChangingPassword] = useState(false);

  const [showDisableTwoFactor, setShowDisableTwoFactor] = useState(false);
  const [twoFactorCode, setTwoFactorCode] = useState('');
  const [showDeleteAccount, setShowDeleteAccount] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] = useState('');

  const [passwordData, setPasswordData] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: '',
  });

  useEffect(() => {
    let cancelled = false;

    async function loadTwoFactorStatus() {
      try {
        const result = await getTwoFactorStatusAction();
        if (!cancelled && result.success && result.data) {
          setTwoFactorEnabled(result.data.enabled);
        }
      } catch (error) {
        console.error('Load two-factor status error:', error);
      }
    }

    async function loadLoginHistory() {
      try {
        const result = await getLoginHistoryAction();
        if (!cancelled && result.success && result.data) {
          setLoginHistory(result.data.history || []);
        }
      } catch (error) {
        console.error('Load login history error:', error);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    loadTwoFactorStatus();
    loadLoginHistory();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleChangePassword() {
    if (passwordData.newPassword !== passwordData.confirmPassword) {
      toast({
        title: 'Error',
        description: 'Passwords do not match',
        variant: 'destructive',
      });
      return;
    }

    try {
      setIsChangingPassword(true);

      // Re-authenticate with the CURRENT password; the backend only accepts an ID token minted in the last
      // five minutes through the password provider.
      const fresh = await reauthenticate('password', passwordData.currentPassword);
      if (fresh.error !== null) {
        toast({ title: 'Error', description: fresh.error, variant: 'destructive' });
        return;
      }

      const result = await changePasswordAction(fresh.idToken, passwordData.newPassword);

      if (!result.success) {
        toast({
          title: 'Error',
          description: result.error || 'Failed to change password',
          variant: 'destructive',
        });
        return;
      }

      // The change revoked this browser's refresh tokens and session cookie. Sign in again with the NEW
      // password to get a fresh ID token, then mint a new session cookie from it.
      const restored = await restoreSessionWithNewPassword(passwordData.newPassword);
      if (!restored) {
        toast({
          title: 'Password changed',
          description: 'Please sign in again with your new password.',
        });
        await signOut(auth).catch(() => undefined);
        router.push('/login');
        return;
      }

      toast({
        title: 'Success',
        description: 'Password changed successfully',
      });

      setShowChangePassword(false);
      setPasswordData({
        currentPassword: '',
        newPassword: '',
        confirmPassword: '',
      });
    } catch (error) {
      console.error('Change password error:', error);
      toast({
        title: 'Error',
        description: 'An unexpected error occurred',
        variant: 'destructive',
      });
    } finally {
      setIsChangingPassword(false);
    }
  }

  async function handleDisableTwoFactor(idToken: string): Promise<string | null> {
    const result = await disableTwoFactorAction(idToken, twoFactorCode);
    if (!result.success) return result.error || 'Failed to disable two-factor authentication';
    setTwoFactorEnabled(false);
    setTwoFactorCode('');
    setShowDisableTwoFactor(false);
    toast({ title: 'Success', description: 'Two-factor authentication disabled' });
    return null;
  }

  async function handleDeleteAccount(idToken: string): Promise<string | null> {
    const result = await deleteAccountAction(idToken);
    if (!result.success) return result.error || 'Failed to delete account';
    await signOut(auth).catch(() => undefined);
    router.push('/');
    return null;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl tracking-tight">Security</h1>
        <p className="text-muted-foreground">Manage your account security and privacy settings</p>
      </div>

      {/* Password Management */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Key className="h-5 w-5 text-theme-accent" />
            Password
          </CardTitle>
          <CardDescription>Update your password to keep your account secure</CardDescription>
        </CardHeader>
        <CardContent>
          <Dialog open={showChangePassword} onOpenChange={setShowChangePassword}>
            <DialogTrigger asChild>
              <Button>Change Password</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Change Password</DialogTitle>
                <DialogDescription>
                  Enter your current password and choose a new one
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
                <div>
                  <Label htmlFor="current-password">Current Password</Label>
                  <Input
                    id="current-password"
                    type="password"
                    value={passwordData.currentPassword}
                    onChange={(e) =>
                      setPasswordData({
                        ...passwordData,
                        currentPassword: e.target.value,
                      })
                    }
                  />
                </div>
                <div>
                  <Label htmlFor="new-password">New Password</Label>
                  <Input
                    id="new-password"
                    type="password"
                    value={passwordData.newPassword}
                    onChange={(e) =>
                      setPasswordData({
                        ...passwordData,
                        newPassword: e.target.value,
                      })
                    }
                  />
                </div>
                <div>
                  <Label htmlFor="confirm-password">Confirm New Password</Label>
                  <Input
                    id="confirm-password"
                    type="password"
                    value={passwordData.confirmPassword}
                    onChange={(e) =>
                      setPasswordData({
                        ...passwordData,
                        confirmPassword: e.target.value,
                      })
                    }
                  />
                </div>
              </div>
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => setShowChangePassword(false)}
                  disabled={isChangingPassword}
                >
                  Cancel
                </Button>
                <Button onClick={handleChangePassword} disabled={isChangingPassword}>
                  {isChangingPassword && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Change Password
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </CardContent>
      </Card>

      {/* Two-factor status. Setup stays hidden until sign-in enforces 2FA (KAN-125, parked); disable is offered when it is on. */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-theme-accent" />
            Two-Factor Authentication
          </CardTitle>
          <CardDescription>An extra verification step when you sign in</CardDescription>
        </CardHeader>
        <CardContent>
          {twoFactorEnabled === null ? (
            <p className="text-sm text-muted-foreground">Two-factor status unavailable</p>
          ) : (
            <p className="text-sm" data-testid="two-factor-status">
              {twoFactorEnabled
                ? 'Two-factor authentication is enabled'
                : 'Two-factor authentication is not enabled'}
            </p>
          )}
          {twoFactorEnabled === true && (
            <Button
              variant="outline"
              className="mt-4"
              onClick={() => setShowDisableTwoFactor(true)}
            >
              Disable 2FA
            </Button>
          )}
        </CardContent>
      </Card>

      {/* Login History */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Clock className="h-5 w-5 text-theme-accent" />
            Login History
          </CardTitle>
          <CardDescription>Review recent activity on your account</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : loginHistory.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date & Time</TableHead>
                  <TableHead>IP Address</TableHead>
                  <TableHead>Location</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loginHistory.map((login) => (
                  <TableRow key={login.id}>
                    <TableCell>{new Date(login.loginAt).toLocaleString()}</TableCell>
                    <TableCell className="font-mono text-sm">
                      {login.ipAddress || 'Unknown'}
                    </TableCell>
                    <TableCell>{login.location || 'Unknown'}</TableCell>
                    <TableCell>
                      <Badge variant={login.successful ? 'default' : 'destructive'}>
                        {login.successful ? 'Success' : 'Failed'}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No login history available
            </p>
          )}
        </CardContent>
      </Card>

      {/* Danger Zone */}
      <Card className="border-destructive/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-destructive">
            <Trash2 className="h-5 w-5" />
            Danger Zone
          </CardTitle>
          <CardDescription>Permanently delete your account and all of its data</CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="destructive" onClick={() => setShowDeleteAccount(true)}>
            Delete Account
          </Button>
        </CardContent>
      </Card>

      <ReauthDialog
        open={showDisableTwoFactor}
        onOpenChange={(open) => {
          setShowDisableTwoFactor(open);
          if (!open) setTwoFactorCode('');
        }}
        title="Disable Two-Factor Authentication"
        description="Confirm your password and enter a code from your authenticator app"
        confirmLabel="Disable 2FA"
        destructive
        canConfirm={/^\d{6}$/.test(twoFactorCode)}
        onConfirm={handleDisableTwoFactor}
      >
        <div>
          <Label htmlFor="disable-2fa-code">Authenticator code</Label>
          <Input
            id="disable-2fa-code"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            value={twoFactorCode}
            onChange={(e) => setTwoFactorCode(e.target.value.replace(/\D/g, ''))}
          />
        </div>
      </ReauthDialog>

      <ReauthDialog
        open={showDeleteAccount}
        onOpenChange={(open) => {
          setShowDeleteAccount(open);
          if (!open) setDeleteConfirmation('');
        }}
        title="Delete Account"
        description="This action cannot be undone. Your account and its data will be permanently deleted."
        confirmLabel="Delete Account"
        destructive
        canConfirm={deleteConfirmation === 'DELETE'}
        onConfirm={handleDeleteAccount}
      >
        <div>
          <Label htmlFor="delete-confirmation">Type DELETE to confirm</Label>
          <Input
            id="delete-confirmation"
            placeholder="DELETE"
            value={deleteConfirmation}
            onChange={(e) => setDeleteConfirmation(e.target.value)}
          />
        </div>
      </ReauthDialog>

      {/* Data export: KAN-114 (switched off, no Prisma access left behind) */}
    </div>
  );
}
