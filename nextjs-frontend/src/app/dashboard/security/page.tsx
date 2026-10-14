'use client';

import { useEffect, useState } from 'react';
import { changePasswordAction, getLoginHistoryAction } from '@/app/actions/user-actions';
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
import { Key, Loader2, Clock } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';

export default function SecurityPage() {
  const { toast } = useToast();
  const [isLoading, setIsLoading] = useState(true);
  const [loginHistory, setLoginHistory] = useState<any[]>([]);
  const [showChangePassword, setShowChangePassword] = useState(false);
  const [isChangingPassword, setIsChangingPassword] = useState(false);

  const [passwordData, setPasswordData] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: '',
  });

  useEffect(() => {
    let cancelled = false;

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

      {/*
        Switched off until their replacements land, with no Prisma access left behind:
        - Data export: KAN-114
        - Two-factor setup/disable (hidden while KAN-125 is parked) and account deletion: KAN-180 (re-authentication dialog)
        - Two-factor status: KAN-179
      */}
    </div>
  );
}
