'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  changePasswordAction,
  deleteAccountAction,
  exportUserDataAction,
  getLoginHistoryAction,
  get2FAStatusAction,
  initiate2FASetupAction,
  verify2FASetupAction,
  disable2FAAction,
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
import {
  Shield,
  Key,
  AlertTriangle,
  Download,
  Trash2,
  Smartphone,
  Loader2,
  Clock,
} from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import QRCode from 'qrcode';

export default function SecurityPage() {
  const router = useRouter();
  const { toast } = useToast();
  const [isLoading, setIsLoading] = useState(true);
  const [loginHistory, setLoginHistory] = useState<any[]>([]);
  const [showChangePassword, setShowChangePassword] = useState(false);
  const [showDeleteAccount, setShowDeleteAccount] = useState(false);
  const [isChangingPassword, setIsChangingPassword] = useState(false);
  const [isDeletingAccount, setIsDeletingAccount] = useState(false);

  // 2FA states
  const [twoFactorEnabled, setTwoFactorEnabled] = useState(false);
  const [showEnable2FA, setShowEnable2FA] = useState(false);
  const [showDisable2FA, setShowDisable2FA] = useState(false);
  const [qrCodeUrl, setQrCodeUrl] = useState<string>('');
  const [twoFactorSecret, setTwoFactorSecret] = useState<string>('');
  const [verificationCode, setVerificationCode] = useState('');
  const [disableCode, setDisableCode] = useState('');
  const [is2FALoading, setIs2FALoading] = useState(false);

  const [passwordData, setPasswordData] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: '',
  });

  const [deleteConfirmation, setDeleteConfirmation] = useState('');

  useEffect(() => {
    loadLoginHistory();
    load2FAStatus();
  }, []);

  async function loadLoginHistory() {
    try {
      setIsLoading(true);
      const result = await getLoginHistoryAction();

      if (result.success && result.data) {
        setLoginHistory(result.data.history || []);
      }
    } catch (error) {
      console.error('Load login history error:', error);
    } finally {
      setIsLoading(false);
    }
  }

  async function load2FAStatus() {
    try {
      const result = await get2FAStatusAction();
      if (result.success && result.data) {
        setTwoFactorEnabled(result.data.twoFactorEnabled || false);
      }
    } catch (error) {
      console.error('Load 2FA status error:', error);
    }
  }

  async function handleEnable2FA() {
    try {
      setIs2FALoading(true);

      const result = await initiate2FASetupAction();

      if (!result.success || !result.data) {
        toast({
          title: 'Error',
          description: result.error || 'Failed to initiate 2FA setup',
          variant: 'destructive',
        });
        return;
      }

      // Generate QR code from URI
      const qrDataUrl = await QRCode.toDataURL(result.data.uri);
      setQrCodeUrl(qrDataUrl);
      setTwoFactorSecret(result.data.secret);
      setShowEnable2FA(true);
    } catch (error: any) {
      console.error('Enable 2FA error:', error);
      toast({
        title: 'Error',
        description: 'Failed to initiate 2FA setup',
        variant: 'destructive',
      });
    } finally {
      setIs2FALoading(false);
    }
  }

  async function handleVerify2FA() {
    if (!verificationCode || verificationCode.length !== 6) {
      toast({
        title: 'Error',
        description: 'Please enter a 6-digit code',
        variant: 'destructive',
      });
      return;
    }

    try {
      setIs2FALoading(true);

      const result = await verify2FASetupAction(verificationCode);

      if (!result.success) {
        toast({
          title: 'Error',
          description: result.error || 'Invalid verification code',
          variant: 'destructive',
        });
        return;
      }

      toast({
        title: 'Success',
        description: 'Two-factor authentication enabled successfully!',
      });

      setShowEnable2FA(false);
      setVerificationCode('');
      setQrCodeUrl('');
      setTwoFactorSecret('');
      setTwoFactorEnabled(true);
    } catch (error: any) {
      console.error('Verify 2FA error:', error);
      toast({
        title: 'Error',
        description: 'Failed to verify 2FA code',
        variant: 'destructive',
      });
    } finally {
      setIs2FALoading(false);
    }
  }

  async function handleDisable2FA() {
    if (!disableCode || disableCode.length !== 6) {
      toast({
        title: 'Error',
        description: 'Please enter a 6-digit code',
        variant: 'destructive',
      });
      return;
    }

    try {
      setIs2FALoading(true);

      const result = await disable2FAAction(disableCode);

      if (!result.success) {
        toast({
          title: 'Error',
          description: result.error || 'Invalid verification code',
          variant: 'destructive',
        });
        return;
      }

      toast({
        title: 'Success',
        description: 'Two-factor authentication disabled successfully',
      });

      setShowDisable2FA(false);
      setDisableCode('');
      setTwoFactorEnabled(false);
    } catch (error: any) {
      console.error('Disable 2FA error:', error);
      toast({
        title: 'Error',
        description: 'Failed to disable 2FA',
        variant: 'destructive',
      });
    } finally {
      setIs2FALoading(false);
    }
  }

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

      const result = await changePasswordAction(
        passwordData.currentPassword,
        passwordData.newPassword
      );

      if (!result.success) {
        toast({
          title: 'Error',
          description: result.error || 'Failed to change password',
          variant: 'destructive',
        });
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

  async function handleDeleteAccount() {
    if (deleteConfirmation !== 'DELETE') {
      toast({
        title: 'Error',
        description: 'Please type "DELETE" to confirm',
        variant: 'destructive',
      });
      return;
    }

    try {
      setIsDeletingAccount(true);

      const result = await deleteAccountAction();

      if (!result.success) {
        toast({
          title: 'Error',
          description: result.error || 'Failed to delete account',
          variant: 'destructive',
        });
        return;
      }

      toast({
        title: 'Success',
        description: 'Account deleted successfully',
      });

      router.push('/');
    } catch (error) {
      console.error('Delete account error:', error);
      toast({
        title: 'Error',
        description: 'An unexpected error occurred',
        variant: 'destructive',
      });
    } finally {
      setIsDeletingAccount(false);
    }
  }

  async function handleExportData() {
    try {
      const result = await exportUserDataAction();

      if (!result.success || !result.data) {
        toast({
          title: 'Error',
          description: result.error || 'Failed to export data',
          variant: 'destructive',
        });
        return;
      }

      // Create a downloadable JSON file
      const dataStr = JSON.stringify(result.data, null, 2);
      const dataBlob = new Blob([dataStr], { type: 'application/json' });
      const url = URL.createObjectURL(dataBlob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `user-data-${new Date().toISOString()}.json`;
      link.click();
      URL.revokeObjectURL(url);

      toast({
        title: 'Success',
        description: 'Data exported successfully',
      });
    } catch (error) {
      console.error('Export data error:', error);
      toast({
        title: 'Error',
        description: 'An unexpected error occurred',
        variant: 'destructive',
      });
    }
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

      {/* Two-Factor Authentication */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Smartphone className="h-5 w-5 text-theme-accent" />
            Two-Factor Authentication
          </CardTitle>
          <CardDescription>Add an extra layer of security to your account</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between rounded-lg border p-4">
            <div className="space-y-0.5">
              <div className="font-medium">2FA Status</div>
              <div className="text-sm text-muted-foreground">
                {twoFactorEnabled
                  ? 'Two-factor authentication is enabled'
                  : 'Two-factor authentication is not enabled'}
              </div>
            </div>
            <Badge variant={twoFactorEnabled ? 'default' : 'secondary'}>
              {twoFactorEnabled ? 'Enabled' : 'Disabled'}
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            Two-factor authentication (2FA) adds an additional layer of protection to your account.
            Once enabled, you'll need to enter both your password and an authentication code from
            your mobile device to sign in.
          </p>

          {!twoFactorEnabled ? (
            <Dialog open={showEnable2FA} onOpenChange={setShowEnable2FA}>
              <DialogTrigger asChild>
                <Button onClick={handleEnable2FA} disabled={is2FALoading}>
                  {is2FALoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  <Shield className="mr-2 h-4 w-4" />
                  Enable 2FA
                </Button>
              </DialogTrigger>
              <DialogContent className="max-w-md">
                <DialogHeader>
                  <DialogTitle>Enable Two-Factor Authentication</DialogTitle>
                  <DialogDescription>
                    Scan this QR code with your authenticator app
                  </DialogDescription>
                </DialogHeader>
                <div className="space-y-4">
                  {qrCodeUrl && (
                    <div className="flex flex-col items-center space-y-4">
                      <div className="rounded-lg border bg-white p-4">
                        <img src={qrCodeUrl} alt="2FA QR Code" className="h-48 w-48" />
                      </div>
                      <div className="w-full space-y-2">
                        <Label className="text-sm font-medium">Or enter this code manually:</Label>
                        <div className="flex items-center gap-2">
                          <Input value={twoFactorSecret} readOnly className="font-mono text-sm" />
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              navigator.clipboard.writeText(twoFactorSecret);
                              toast({
                                title: 'Copied',
                                description: 'Secret key copied to clipboard',
                              });
                            }}
                          >
                            Copy
                          </Button>
                        </div>
                      </div>
                      <div className="w-full space-y-2">
                        <Label htmlFor="verification-code">
                          Enter the 6-digit code from your app:
                        </Label>
                        <Input
                          id="verification-code"
                          type="text"
                          placeholder="000000"
                          maxLength={6}
                          value={verificationCode}
                          onChange={(e) => setVerificationCode(e.target.value.replace(/\D/g, ''))}
                          className="text-center font-mono text-lg tracking-widest"
                        />
                      </div>
                    </div>
                  )}
                </div>
                <DialogFooter>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setShowEnable2FA(false);
                      setVerificationCode('');
                      setQrCodeUrl('');
                      setTwoFactorSecret('');
                    }}
                    disabled={is2FALoading}
                  >
                    Cancel
                  </Button>
                  <Button
                    onClick={handleVerify2FA}
                    disabled={is2FALoading || verificationCode.length !== 6}
                  >
                    {is2FALoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    Verify & Enable
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          ) : (
            <Dialog open={showDisable2FA} onOpenChange={setShowDisable2FA}>
              <DialogTrigger asChild>
                <Button variant="destructive" disabled={is2FALoading}>
                  {is2FALoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Disable 2FA
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Disable Two-Factor Authentication</DialogTitle>
                  <DialogDescription>Enter your current 2FA code to confirm</DialogDescription>
                </DialogHeader>
                <div className="space-y-4 py-4">
                  <div className="space-y-2">
                    <Label htmlFor="disable-code">
                      Enter the 6-digit code from your authenticator app:
                    </Label>
                    <Input
                      id="disable-code"
                      type="text"
                      placeholder="000000"
                      maxLength={6}
                      value={disableCode}
                      onChange={(e) => setDisableCode(e.target.value.replace(/\D/g, ''))}
                      className="text-center font-mono text-lg tracking-widest"
                    />
                  </div>
                  <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4">
                    <p className="text-sm text-destructive">
                      <AlertTriangle className="mr-2 inline h-4 w-4" />
                      Warning: Disabling 2FA will make your account less secure.
                    </p>
                  </div>
                </div>
                <DialogFooter>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setShowDisable2FA(false);
                      setDisableCode('');
                    }}
                    disabled={is2FALoading}
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={handleDisable2FA}
                    disabled={is2FALoading || disableCode.length !== 6}
                  >
                    {is2FALoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    Disable 2FA
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
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

      {/* Data Export */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Download className="h-5 w-5 text-theme-accent" />
            Data Export
          </CardTitle>
          <CardDescription>Download a copy of your personal data</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="mb-4 text-sm text-muted-foreground">
            Export all your account data including profile information, settings, and activity
            history.
          </p>
          <Button onClick={handleExportData} variant="outline">
            <Download className="mr-2 h-4 w-4" />
            Export My Data
          </Button>
        </CardContent>
      </Card>

      {/* Delete Account */}
      <Card className="border-destructive">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-destructive">
            <AlertTriangle className="h-5 w-5" />
            Danger Zone
          </CardTitle>
          <CardDescription>Permanently delete your account and all associated data</CardDescription>
        </CardHeader>
        <CardContent>
          <Dialog open={showDeleteAccount} onOpenChange={setShowDeleteAccount}>
            <DialogTrigger asChild>
              <Button variant="destructive">
                <Trash2 className="mr-2 h-4 w-4" />
                Delete Account
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle className="text-destructive">Delete Account</DialogTitle>
                <DialogDescription>
                  This action cannot be undone. This will permanently delete your account and remove
                  your data from our servers.
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
                <div>
                  <Label htmlFor="delete-confirmation">
                    Type <span className="font-bold">DELETE</span> to confirm
                  </Label>
                  <Input
                    id="delete-confirmation"
                    value={deleteConfirmation}
                    onChange={(e) => setDeleteConfirmation(e.target.value)}
                    placeholder="DELETE"
                  />
                </div>
              </div>
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowDeleteAccount(false);
                    setDeleteConfirmation('');
                  }}
                  disabled={isDeletingAccount}
                >
                  Cancel
                </Button>
                <Button
                  variant="destructive"
                  onClick={handleDeleteAccount}
                  disabled={isDeletingAccount || deleteConfirmation !== 'DELETE'}
                >
                  {isDeletingAccount && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Delete Account
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </CardContent>
      </Card>
    </div>
  );
}
