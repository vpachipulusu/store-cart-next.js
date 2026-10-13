# Profile, settings and security

**Who this is for:** every signed-in StoreCart user.

## Edit your profile

1. In the top bar, select **Profile**.
2. Under **Personal Information**, update any of these:
   - **Display Name** (at least 2 characters)
   - **Bio** (up to 500 characters)
   - **Location**
   - **Website** (must be a full web address, such as `https://example.com`)
   - **Phone Number**
3. Select **Save Changes**. You see "Profile updated successfully".

To undo edits you haven't saved, select **Cancel**.

Your **Email** is shown but can't be changed here.

### Profile picture (may change)

The **Profile Picture** section has an **Upload Photo** button. Photo upload is **not working yet**
and **may change**. If you signed in with Google or GitHub, your picture from that account may be
shown instead.

## Change your preferences

1. In the top bar, select **Settings**.
2. Change any of these:
   - **Theme**: Light, Dark or System.
   - **Email Notifications**: turn emails about your account activity on or off.
   - **Language**: your preferred language.
   - **Timezone**: used to show times correctly.
3. Select **Save Settings**. You see "Settings updated successfully".

To go back to your saved values, select **Reset**.

> **May change:** the language and timezone options are limited, and some preferences may not
> affect every screen yet.

## Security

Everything in this section is on the **Security** page. Select **Security** in the top bar.

### Change your password

Use this when you know your current password. If you've forgotten it, see
[Reset a forgotten password](getting-started.md#reset-a-forgotten-password).

1. Under **Password**, select **Change Password**.
2. Enter your **Current Password**, **New Password** and **Confirm New Password**.
3. Select **Change Password**. You see "Password changed successfully".

Your new password must be at least 8 characters long.

### Two-factor authentication (2FA)

> **Coming soon: sign-in will ask for your code. Until then, turning 2FA on does not add a check
> at sign-in.** You can set up two-factor authentication today, and it is a required StoreCart
> feature, but it is not a top priority right now. Signing in still needs only your password (or
> Google or GitHub). The Security page explains that enabling 2FA saves your setup without
> adding protection at sign-in. Keep a strong, unique password. This page will be updated when
> sign-in checks the code.

Two-factor authentication uses a 6-digit code from an authenticator app on your phone (for example
Google Authenticator, Microsoft Authenticator or 1Password).

#### Turn on 2FA

1. Install an authenticator app on your phone, if you don't have one.
2. Under **Two-Factor Authentication**, select **Enable 2FA**.
3. Scan the QR code with your authenticator app.
   - Can't scan? Select **Copy** next to "Or enter this code manually" and type the code into your
     app instead.
4. Enter the 6-digit code your app shows.
5. Select **Verify & Enable**. The **2FA Status** changes to **Enabled**.

Keep your phone and authenticator app safe. You need them to turn 2FA off again.

#### Turn off 2FA

1. Under **Two-Factor Authentication**, select **Disable 2FA**.
2. Enter the current 6-digit code from your authenticator app.
3. Select **Disable 2FA**. The status changes to **Disabled**.

> **Coming soon:** asking for your 2FA code at sign-in. Recovery options for a lost phone are not
> available yet, so keep your authenticator app safe. You need a current code to turn 2FA off.

### Review your login history

**Login History** lists your recent sign-ins with:

- **Date & Time**
- **IP Address**
- **Location** (when known)
- **Status**: **Success** or **Failed**

Several **Failed** entries you don't recognise may mean someone is trying to get into your
account. [Change your password](#change-your-password) straight away.

### Export your data (being removed)

The **Data Export** section has an **Export My Data** button. Data export is **being removed** from
this release and will return in a redesigned form. It may stop working at any time. See
[What's coming](roadmap.md#removed-for-redesign).

### Delete your account

**Danger Zone** lets you delete your account. This **cannot be undone**.

Before you start:

- If you have a paid plan, check [Plans and billing](plans-and-billing.md) first. Download any
  invoices you need, because you will lose access to them.

To delete your account:

1. Under **Danger Zone**, select **Delete Account**.
2. Read the warning, then type `DELETE` in the box.
3. Select **Delete Account**.

Your account and its data are removed and you are signed out.

> **May change:** once organisations and stores arrive, deleting an account will work differently
> (for example, an organisation owner may need to hand over or close the organisation first).
