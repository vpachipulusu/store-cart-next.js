# Parity inventory — boilerplate server actions and API routes (KAN-113)

**Purpose.** This file lists every server action, API route and Prisma-querying page in the Next.js boilerplate (`nextjs-frontend/`), with what each one does and which Jira story ports it to FastAPI or switches it off. It is the checklist for the Foundation port (E3–E6) and for the security exit rule in [storecart-plan.md](storecart-plan.md#foundation-scope-council-decision-2026-10-11): every Prisma path is moved to the API or switched off. Cut features go to E22 (KAN-114) and are **switched off, never left on Prisma**.

**Source commit:** `5fee4b8` (branch `test/KAN-113-parity-baseline`), refreshed after rebasing on `main` at `1105b29` (KAN-122 removed two actions and three auth routes; KAN-134 made the Stripe clients lazy). Taken from the code, not from docs. Removed items stay in the tables, struck through, so the porting history is kept.

**Keeping it updated.** When a story ports or switches off an item, add `✅ <PR>` to its Porting story cell. Do not delete rows until KAN-51 removes Prisma. If the boilerplate changes before then, re-run these commands and update the counts:

```bash
cd nextjs-frontend
grep -cE '^export (async function|const)' src/app/actions/*.ts src/app/actions/admin/*.ts   # actions per file
find src/app/api -name route.ts                                                            # routes
grep -rl "@/lib/db/client" src | sort                                                      # Prisma importers
```

**Conventions.**
- `user` auth means the `session` cookie is checked with `adminAuth.verifySessionCookie(cookie, true)` (revocation checked), then `users` is looked up by `firebaseUid` (the file-local `getAuthenticatedUserId()`).
- `admin:<perm>` means the same check, plus an `admin_users` row, plus `hasPermission(perm)` (or `*`).
- Every action returns `{ success, data?, error? }`. Every action also has a catch-all error: `error.message` from Prisma, Stripe or Firebase is returned to the client as-is. That is "msg" in the tables.
- "Unauth" = `'Unauthorized'`. Admin actions return `'Unauthorized'` both when the user is not signed in and when a permission is missing.
- "UI" = called from a page or component. "unused" = no importer outside `src/app/actions/`.

## Summary

| Source file | Exports | Used by UI | Porting stories |
|---|---:|---:|---|
| actions/auth-actions.ts | 6 (8 before KAN-122) | 2 | KAN-37, KAN-41 |
| actions/font-actions.ts | 1 | 1 | KAN-118 (switch off) / KAN-51 |
| actions/theme-actions.ts | 1 | 1 | KAN-118 (switch off) / KAN-51 |
| actions/notification-actions.ts | 4 | 2 | KAN-40 (switch off) |
| actions/subscription-actions.ts | 14 | 11 | KAN-43, KAN-45 |
| actions/user-actions.ts | 19 | 13 | KAN-38, KAN-39, KAN-41, KAN-40/KAN-120 (switch off) |
| actions/admin/user-actions.ts | 10 | 0 | KAN-47, KAN-119/KAN-40 (switch off) |
| actions/admin/subscription-actions.ts | 9 | 0 | KAN-48, KAN-119 (switch off) |
| actions/admin/seo-actions.ts | 11 | 2 | KAN-116 (switch off) |
| actions/admin/settings-actions.ts | 17 | 2 | KAN-117, KAN-118, KAN-119 (switch off), KAN-49 |
| **Actions total** | **92** (94 before KAN-122) | **34** | |
| API routes (`route.ts` files) | 3 files / 4 handlers (6 / 10 before KAN-122) | 1 (clear-session) | KAN-41, KAN-44, KAN-51 |
| Pages and layouts querying Prisma | 12 | — | KAN-45, KAN-50 (+ E22 switch-offs) |
| Shared server modules importing `db` | 8 | — | KAN-40, KAN-42–KAN-44, KAN-46, KAN-49, KAN-51 |

| Porting story | Actions | Routes | Pages |
|---|---:|---:|---:|
| KAN-37 Firebase session auth | 3 (logoutAction, verifyTokenAction, getCurrentSessionAction); ~~syncUserAction~~ removed in KAN-122 | ~~3 (login, logout, signup)~~ removed in KAN-122 | — |
| KAN-41 Frontend auth/profile use API | 3 (loginAction, signUpAction, verifyEmailAction); ~~requestPasswordResetAction~~ removed in KAN-122 + all KAN-37/38/39 actions on the frontend side | 1 (clear-session) | dashboard/layout |
| KAN-38 Profile, settings, account | 9 | — | — |
| KAN-39 2FA (TOTP) | 4 | — | — |
| KAN-43 / KAN-45 Org billing | 14 | — | pricing (KAN-45) |
| KAN-44 Stripe webhook | — | 1 | — |
| KAN-47 Admin users API | 8 | — | — |
| KAN-48 Admin subscriptions API | 6 | — | — |
| KAN-49 Audit log API | 1 | — | — |
| KAN-50 Admin/dashboard pages | — | — | 12 (all, switch-offs included) |
| KAN-51 Remove Prisma/secrets | font/theme fallbacks | ~~test-logging~~ (deleted, KAN-146) | — |
| **E22 switch off** KAN-40 notifications | 9 | — | dropdown and panels |
| **E22 switch off** KAN-116 SEO/redirects | 11 | — | admin/seo |
| **E22 switch off** KAN-117 email templates | 4 | — | admin/settings (part) |
| **E22 switch off** KAN-118 flags/app settings | 13 (incl. getActiveFont/getActiveTheme) | — | admin/settings (part) |
| **E22 switch off** KAN-119 analytics/stats | 5 | — | admin/analytics, stats cards |
| **E22 switch off** KAN-120 data export | 1 | — | — |

How the rows add up: 3 (KAN-37) + 3 (KAN-41 deletes) + 9 (KAN-38) + 4 + 14 + 8 + 6 + 1 + 9 + 11 + 4 + 13 + 5 + 1 = 91. The 92nd is `changePasswordAction`, which has no clear story. (Before KAN-122: 4 + 4 + … = 93, plus `changePasswordAction` = 94.) Some rows map to "delete, no port":
- loginAction, signUpAction and verifyEmailAction (requestPasswordResetAction already removed in KAN-122)
- the aliases deleteUserAccountAction and getUserLoginHistoryAction

updateUserSubscriptionAction is counted under KAN-48, but that mapping is uncertain; see ⚠ Notes.

---

## src/app/actions/auth-actions.ts (6; 8 before KAN-122)

| Action | Auth | Inputs | Output (`data`) | Errors | Side effects | Porting story |
|---|---|---|---|---|---|---|
| loginAction | none | `email, password: string`. Zod `loginSchema` (emailSchema, password min 1) | `{message}` | first Zod msg; msg | none. A no-op validator (Firebase client signs in). Unused | KAN-41: delete (client Firebase SDK + KAN-37 session) |
| signUpAction | none | `email, password, displayName?`. Zod `signUpSchema` (passwordSchema, displayName min 2) | `{message}` | first Zod msg; msg | none. A no-op. Unused | KAN-41: delete |
| logoutAction | cookie (unverified ok) | — | `{message}` | msg | Firebase `verifySessionCookie(…, false)` + `revokeRefreshTokens` (errors swallowed); deletes cookies `session`, `email-verified`. **UI** (admin and dashboard headers) | KAN-37 `DELETE /v1/auth/session` + KAN-41 |
| verifyTokenAction | Firebase ID token | `idToken: string` (the `metadata.selectedPlan` argument was removed in KAN-122) | `{user:{id, firebaseUid, email, emailVerified, displayName, avatarUrl, subscriptionTier, subscriptionStatus, isAdmin}}` | `'Email not found in token'`; msg (bad token) | Firebase `verifyIdToken`, `getUser`, `createSessionCookie` (5 days). Creates or updates `users` (new users always start on `free` since KAN-122). Creates `user_settings`. Creates a `login_history` row with geo-IP lookup (`getLocationFromIP`). Notifications: `notifyEmailVerified`, `notifyNewDeviceLogin`. Sets cookies `session` (httpOnly) and `email-verified` (not httpOnly). **UI** (login, signup, OAuth, verify-email, use-session-refresh) | KAN-37 `POST /v1/auth/session` + KAN-41. Notification side effects: switch off (KAN-40) |
| ~~syncUserAction~~ (removed, KAN-122) | **none** ⚠ | `firebaseUid: string` | `{user}` (full row) | msg | Firebase `getUser`; upserts `users`. Unused | ✅ Deleted (KAN-122, PR #4) |
| getCurrentSessionAction | user (cookie) | — | `{user:{…, isAdmin, settings}}` | `'No session found'`, `'User not found'`, msg | On failure, deletes cookies `session` and `email-verified`. Unused | KAN-37/KAN-38 `GET /v1/me` + KAN-41 |
| ~~requestPasswordResetAction~~ (removed, KAN-122) | **none** ⚠ | `email` (emailSchema) | `{message, resetLink}` ⚠ | `'Invalid email format'`; msg (reveals unknown email) | Firebase `generatePasswordResetLink`. **No email is sent. The link is returned to the caller.** Unused | KAN-41: use client `sendPasswordResetEmail`. ✅ Action deleted (KAN-122, PR #4) |
| verifyEmailAction | none | `oobCode: string` | `{message}` | msg | Firebase **client** SDK `applyActionCode` called on the server. Unused | KAN-41: client-side only; delete |

## src/app/actions/font-actions.ts (1) and theme-actions.ts (1)

| Action | Auth | Inputs | Output | Errors | Side effects | Porting story |
|---|---|---|---|---|---|---|
| getActiveFont (`unstable_cache`) | none | — | `FontId` (not an envelope) | none; falls back to `DEFAULT_FONT` | reads `app_settings[app_font]`; cache tag `active-font`, revalidate 3600 s. **UI** root `layout.tsx` | E22 — switch off (KAN-118): return `DEFAULT_FONT`. Prisma import removed in KAN-51 |
| getActiveTheme (`unstable_cache`) | none | — | theme name `string` | none; falls back to `DEFAULT_THEME` | reads `app_settings[active_theme]`; tag `active-theme`, 3600 s. **UI** root `layout.tsx` | E22 — switch off (KAN-118): return `DEFAULT_THEME`. KAN-51 |

## src/app/actions/notification-actions.ts (4)

All are `user` auth and all are E22 — switch off (KAN-40). KAN-41's AC switches off the notifications dropdown.

| Action | Auth | Inputs | Output | Errors | Side effects | Porting story |
|---|---|---|---|---|---|---|
| getNotificationsAction | user | `limit = 10` (unbounded) | `{notifications[], unreadCount}` | Unauth; msg | reads `notifications`. Unused | E22 — switch off (KAN-40) |
| markNotificationAsReadAction | user | `notificationId: string` | `{message}` | Unauth; `'Notification not found'` (owner check); msg | updates `notifications.read`. **UI** dropdown | E22 — switch off (KAN-40) |
| markAllNotificationsAsReadAction | user | — | `{count}` | Unauth; msg | `updateMany notifications`. **UI** dropdown | E22 — switch off (KAN-40) |
| deleteNotificationAction | user | `notificationId` | `{message}` | Unauth; `'Notification not found'`; msg | deletes `notifications`. Unused. Same name as the export in user-actions ⚠ | E22 — switch off (KAN-40) |

## src/app/actions/subscription-actions.ts (14)

All are `user` auth (`'Unauthorized'` when there is no session). This file uses its own `new Stripe(STRIPE_SECRET_KEY)`. Billing moves to the organisation: endpoints in KAN-43, frontend in KAN-45. Only OWNER and ADMIN may manage billing.

| Action | Auth | Inputs | Output | Errors | Side effects | Porting story |
|---|---|---|---|---|---|---|
| getSubscriptionStatusAction | user | — | `{subscriptionTier, subscriptionStatus, currentPeriodEnd, stripeSubscription:{id, status, currentPeriodEnd, cancelAtPeriodEnd, canceledAt}\|null}` | Unauth; `'User not found'`; msg (Stripe errors swallowed) | Stripe `subscriptions.retrieve`. **UI** subscription-success-handler | KAN-43 / KAN-45 |
| createCheckoutSessionAction | user | `tier: 'pro'\|'enterprise', billingPeriod: 'monthly'\|'yearly', successUrl, cancelUrl` (Zod `createCheckoutSessionSchema`, URLs `.url()`) | `{sessionId, url}` | Unauth; Zod msg; `` `Price not configured for ${tier} ${billingPeriod} plan` ``; `'User not found'`; Stripe msg | Stripe `customers.create` (first time) and writes `users.stripeCustomerId`; `checkout.sessions.create`. Cookies `checkout_token` and `checkout_session` (httpOnly, 10 min). Any success/cancel host is accepted ⚠. **UI** pricing-card | KAN-43 / KAN-45 |
| verifyUpgradeSessionAction | user | — (reads checkout cookies) | `{valid, reason?}` | Unauth; `'User not found'`; msg | Deletes the checkout cookies when valid. The token is never compared with anything ⚠. **UI** | KAN-45 (or drop: read status from the API) |
| createBillingPortalSessionAction | user | `returnUrl: string` (not validated ⚠) | `{url}` | Unauth; `'No billing information found'`; Stripe msg | Stripe `billingPortal.sessions.create`. **UI** billing | KAN-43 / KAN-45 |
| cancelSubscriptionAction | user | — | `{message, cancelAt}` | Unauth; `'No active subscription found'`; Stripe msg | Stripe `subscriptions.update(cancel_at_period_end: true)`. No database write (the webhook syncs it). **UI** | KAN-43 / KAN-45 |
| resumeSubscriptionAction | user | — | `{message}` | Unauth; `'No subscription found'`; "already been canceled…"; "never completed…"; `` `Subscription status is ${status}…` ``; Stripe msg | Stripe `retrieve` then `update(cancel_at_period_end: false)`. **UI** | KAN-43 / KAN-45 |
| updateSubscriptionAction | user | `newPriceId: string` (no allow-list ⚠) | `{message, subscription:{id, status}}` | Unauth; `'No active subscription found'`; Stripe msg | Stripe `subscriptions.update` (create_prorations). Unused | KAN-43 (plan change, server-side price map) |
| getSubscriptionInvoicesAction | user | `limit = 10` | `{invoices:[{id, amount, currency, status, created, pdfUrl, hostedUrl}], hasMore}` | Unauth; `'No billing information found'`; Stripe msg | Stripe `invoices.list`. **UI** | KAN-43 / KAN-45 |
| getUpcomingInvoiceAction | user | — | `{amount, currency, periodEnd}` | Unauth; `'No active subscription found'`; Stripe msg | Stripe `invoices.retrieveUpcoming`, which was removed in the pinned API version `2025-08-27.basil` ⚠. Unused | KAN-43 (use `createPreview`) or drop |
| hasActiveSubscriptionAction | user | — | `{hasActiveSubscription}` | Unauth; `'User not found'`; msg | reads `users`. Unused | KAN-43 (derive from the org) |
| getSubscriptionDetailsAction | user | — | `{subscriptionTier, subscriptionStatus, stripeStatus, billingPeriod, autoRenewal, currentPeriodEnd, hasStripeCustomer}` | Unauth; `'User not found'`; msg | Stripe `subscriptions.retrieve` (expand price). **UI** | KAN-43 / KAN-45 |
| getPaymentMethodsAction | user | — | `{paymentMethods:[{id, brand, last4, expMonth, expYear, isDefault}], defaultPaymentMethodId}` (empty when there is no customer) | Unauth; Stripe msg | Stripe `customers.retrieve`, `paymentMethods.list`. **UI** | KAN-43 / KAN-45 |
| deletePaymentMethodAction | user | `paymentMethodId: string` | `{message}` | Unauth; `'Invalid payment method ID'`; `'No billing information found'`; "Cannot delete payment method while auto-renewal is active…"; `'Payment method is not attached to any customer'`; `'Payment method not found or does not belong to your account'`; Stripe msg | Stripe `subscriptions.retrieve`, `paymentMethods.retrieve` and `detach`. **UI** | KAN-43 / KAN-45 |
| setDefaultPaymentMethodAction | user | `paymentMethodId: string` | `{message}` | Unauth; `'Invalid payment method ID'`; `'No billing information found'`; `'Payment method does not belong to your account'`; Stripe msg | Stripe `paymentMethods.attach` (if unattached); `customers.update`; `subscriptions.update` (error swallowed). **UI** | KAN-43 / KAN-45 |

## src/app/actions/user-actions.ts (19)

All are `user` auth (`'Unauthorized'`).

| Action | Auth | Inputs | Output | Errors | Side effects | Porting story |
|---|---|---|---|---|---|---|
| getUserProfileAction | user | — | `{user:{id, email, emailVerified, displayName, bio, avatarUrl, location, website, phoneNumber, subscriptionTier, subscriptionStatus, createdAt, settings}}` | Unauth; `'User not found'`; msg | reads `users` and `user_settings`. **UI** profile | KAN-38 `GET /v1/me` + KAN-41 |
| updateUserProfileAction | user | `data` (Zod `profileUpdateSchema`; the raw `data` is written, not `validation.data`) | `{user}`: the **full `users` row** ⚠ | Unauth; Zod msg; msg | updates `users`. **UI** profile | KAN-38 + KAN-41 |
| updateUserAvatarAction | user | `avatarUrl` (`z.string().url()`) | `{avatarUrl}` | Unauth; `'Invalid avatar URL'`; msg | updates `users.avatarUrl`. **UI** | KAN-38 + KAN-41 |
| getUserSettingsAction | user | — | `{settings}` | Unauth; msg | creates default `user_settings` if missing. **UI** settings | KAN-38 + KAN-41 |
| updateUserSettingsAction | user | `data` (Zod `userSettingsSchema`: theme, emailNotifications, language, timezone) | `{settings}` | Unauth; Zod msg; msg | upserts `user_settings`. **UI** | KAN-38 + KAN-41 |
| getUserNotificationsAction | user | `limit = 10, offset = 0` | `{notifications, totalCount, unreadCount}` | Unauth; msg | reads `notifications`. Unused. Duplicate ⚠ | E22 — switch off (KAN-40) |
| markNotificationReadAction | user | `notificationId` | `{message}` | Unauth; `'Notification not found'`; msg | updates `notifications`. Unused. Duplicate ⚠ | E22 — switch off (KAN-40) |
| markAllNotificationsReadAction | user | — | `{message}` | Unauth; msg | `updateMany notifications`. Unused. Duplicate ⚠ | E22 — switch off (KAN-40) |
| deleteNotificationAction | user | `notificationId` | `{message}` | Unauth; `'Notification not found'`; msg | deletes `notifications`. Unused. Duplicate name ⚠ | E22 — switch off (KAN-40) |
| getUserLoginHistoryAction | user | `limit = 10, offset = 0` | `{loginHistory, totalCount}` | Unauth; msg | reads `login_history`. Unused. Duplicate of getLoginHistoryAction ⚠ | KAN-38 (one endpoint); delete |
| changePasswordAction | user | `currentPassword, newPassword: string` (len ≥ 8, no Zod) | `{message}` | Unauth; `'New password must be at least 8 characters long'`; `'User not found'`; `'Server configuration error'`; `'Current password is incorrect'`; msg | Calls the Firebase REST API `accounts:signInWithPassword` to re-verify. Firebase `updateUser(password)`. `notifyPasswordChanged`. Other sessions are not revoked; no rate limit. **UI** security | ⚠ No explicit story: KAN-41 (client `reauthenticate` + `updatePassword`) or KAN-38 |
| exportUserDataAction | user | — | `{profile, settings, loginHistory[], notifications[], subscription}` | Unauth; `'User not found'`; msg | reads `users`, `user_settings`, `login_history`, `notifications`. **UI** security | E22 — switch off (KAN-120). The button is off per KAN-41 |
| getLoginHistoryAction | user | `limit = 10, offset = 0` | `{history, totalCount}` | Unauth; msg | reads `login_history`. **UI** security | KAN-38 + KAN-41 |
| deleteAccountAction | user (no re-auth ⚠) | — | `{message}` | Unauth; `'User not found'`; msg | `lib/stripe/subscriptions.cancelSubscription(id, true)` (error swallowed). Firebase `deleteUser`. Deletes `users` (cascade). Deletes cookies `session` and `email-verified`. No audit log. **UI** security | KAN-38 (`DELETE /v1/me`) + KAN-41. Org billing interplay: KAN-43. The frontend Stripe helpers it used were removed in KAN-50 |
| deleteUserAccountAction | user | — | same as deleteAccountAction (alias) | same | same. Unused. Duplicate ⚠ | delete (alias) |
| initiate2FASetupAction | user | — | `{uri, secret}` | Unauth; `'User not found'`; `'2FA is already enabled'`; msg | writes `users.twoFactorSecret` (plaintext). **UI** | KAN-39 |
| verify2FASetupAction | user | `token: string` | `{message}` | Unauth; `'2FA setup not initiated'`; `'Invalid verification code'`; msg | sets `users.twoFactorEnabled = true`. **UI** | KAN-39 |
| disable2FAAction | user | `token: string` | `{message}` | Unauth; `'2FA is not enabled'`; `'Invalid verification code'`; msg | clears `twoFactorEnabled` and `twoFactorSecret`. **UI** | KAN-39 |
| get2FAStatusAction | user | — | `{twoFactorEnabled}` | Unauth; `'User not found'`; msg | reads `users`. **UI** | KAN-39 |

## src/app/actions/admin/user-actions.ts (10)

Auth is `admin:<perm>` through a file-local `getAuthenticatedAdmin()` and `hasPermission()`. None of these actions is called from the UI: the admin pages query Prisma directly.

| Action | Auth | Inputs | Output | Errors | Side effects | Porting story |
|---|---|---|---|---|---|---|
| getAllUsersAction | admin:users.read | `page = 1, limit = 20, filters?: {search, subscriptionTier, subscriptionStatus, emailVerified, isAdmin}` (the `userFiltersSchema` is declared but **never parsed**; `limit` is unbounded) | `{users:[{id, firebaseUid, email, emailVerified, displayName, avatarUrl, subscriptionTier, subscriptionStatus, isAdmin, createdAt, lastLoginAt}], pagination:{page, limit, totalCount, totalPages}}` | Unauth; msg | reads `users` | KAN-47 |
| getUserByIdAction | admin:users.read | `userId` | `{user}`: the full row plus settings, adminUser, 10 logins and 10 notifications (includes `twoFactorSecret` ⚠) | Unauth; `'User not found'`; msg | reads | KAN-47 (drop notifications: KAN-40) |
| updateUserAction | admin:users.update | `userId`, `data` (Zod `updateUserSchema`: email, displayName, emailVerified, subscriptionTier, subscriptionStatus) | `{user}` | Unauth; Zod msg; msg | updates `users` (Firebase is not updated when the email changes ⚠); audit `user.updated` | KAN-47 |
| deleteUserAction | admin:users.delete | `userId` | `{message}` | Unauth; `'User not found'`; msg | Firebase `deleteUser` (error swallowed); deletes `users`; audit `user.deleted`. The Stripe subscription is not cancelled | KAN-47 |
| grantAdminRoleAction | admin:admins.create | `userId`, `{role: 'admin'\|'super_admin', permissions: string[]}` (Zod `grantAdminRoleSchema`) | `{adminUser}` | Unauth; Zod msg; msg | upserts `admin_users`; audit `admin.granted`. Any permission can be granted, including `*` ⚠ | KAN-47 |
| revokeAdminRoleAction | admin:admins.delete | `userId` | `{message}` | Unauth; msg (P2025 if not an admin) | deletes `admin_users`; audit `admin.revoked`. Admins can revoke themselves or the last super admin | KAN-47 |
| getUserStatsAction | admin:users.read | — | `{totalUsers, verifiedUsers, adminUsers, activeSubscriptions, newUsersThisMonth}` | Unauth; msg | counts | E22 — switch off (KAN-119) |
| banUserAction | admin:users.update | `userId, reason?` | `{message}` | Unauth; `'User not found'`; msg | Firebase `updateUser(disabled: true)`; audit `user.banned` | KAN-47 |
| unbanUserAction | admin:users.update | `userId` | `{message}` | Unauth; `'User not found'`; msg | Firebase `updateUser(disabled: false)`; audit `user.unbanned` | KAN-47 |
| sendUserNotificationAction | admin:notifications.create | `userId, {type, title, message, link?}` (not validated) | `{message}` | Unauth; msg | creates `notifications`; no audit | E22 — switch off (KAN-40). Out of scope per the KAN-47 AC |

## src/app/actions/admin/subscription-actions.ts (9)

Auth is `admin:<perm>`. This file uses its own `new Stripe(…)`. None of these actions is called from the UI.

| Action | Auth | Inputs | Output | Errors | Side effects | Porting story |
|---|---|---|---|---|---|---|
| getAllSubscriptionsAction | admin:subscriptions.read | `page = 1, limit = 20, filters?: {status?, tier?}` | `{subscriptions:[{id, email, displayName, subscriptionTier, subscriptionStatus, stripeSubscriptionId, stripePriceId, stripeCurrentPeriodEnd, createdAt}], pagination}` | Unauth; msg | reads `users` | KAN-48 (per organisation) |
| getSubscriptionStatsAction | admin:subscriptions.read | — | `{totalSubscriptions, activeSubscriptions, canceledSubscriptions, trialSubscriptions, subscriptionsByTier, estimatedMonthlyRevenue}` (the revenue field is a count) | Unauth; msg | counts and `groupBy` | E22 — switch off (KAN-119) |
| getUserSubscriptionDetailsAction | admin:subscriptions.read | `userId` | `{user, stripeSubscription (raw), stripeInvoices (raw, 10)}` | Unauth; `'User not found'`; msg (Stripe errors swallowed) | Stripe `subscriptions.retrieve`, `invoices.list` | KAN-48 |
| updateUserSubscriptionAction | admin:subscriptions.update | `userId, {subscriptionTier, subscriptionStatus}` (Zod: free strings) | `{user}` | Unauth; Zod msg; msg | updates `users` only, so the database drifts from Stripe; audit `subscription.updated` | ⚠ Not in the KAN-48 AC (list, detail, cancel, refund, grant). Drop or fold into the grant flow |
| cancelUserSubscriptionAction | admin:subscriptions.update | `userId, immediately = false` | `{message}` | Unauth; `'No active subscription found'`; Stripe msg | Stripe `subscriptions.cancel` or `update(cancel_at_period_end)`. If immediate, updates `users` (status canceled, ids null). Audit `subscription.canceled` | KAN-48 |
| refundSubscriptionPaymentAction | admin:subscriptions.refund | `userId, amount?: number` (not validated ⚠) | `{message, refund:{id, amount, status}}` | Unauth; `'No billing information found'`; `'No charges found'`; Stripe msg | Stripe `charges.list(limit 1)` then `refunds.create` on the **latest** charge only; audit `subscription.refunded` | KAN-48 |
| grantFreeSubscriptionAction | admin:subscriptions.grant | `userId, tier: string, durationInDays: number` (not validated) | `{message, user}` | Unauth; msg | updates `users` (tier, status active, period end); audit `subscription.granted`. Nothing expires it except the period-end check | KAN-48 |
| getSubscriptionRevenueAction | admin:subscriptions.read | `startDate?, endDate?: Date` | `{totalRevenue, revenueByMonth:[{month, amount}]}` | Unauth; msg | one Stripe `invoices.list` per customer (N+1, 100-invoice cap) | E22 — switch off (KAN-119) |
| syncStripeSubscriptionsAction | admin:subscriptions.sync | — | `{message, syncedCount, errorCount}` | Unauth; msg | Stripe `retrieve` per user; updates `users`; no audit | E22 — switch off (KAN-119, bulk sync) |

## src/app/actions/admin/seo-actions.ts (11)

All are E22 — switch off (KAN-116, per-store SEO and redirects). Auth is `admin:seo.*`, except where marked.

| Action | Auth | Inputs | Output | Errors | Side effects | Porting story |
|---|---|---|---|---|---|---|
| getAllSEOMetaAction | admin:seo.read | — | `{seoMeta[]}` | Unauth; msg | reads `seo_meta` | E22 — switch off (KAN-116) |
| getSEOMetaByPageAction | admin:seo.read | `page` | `{seoMeta}` | Unauth; `'SEO meta not found'`; msg | reads | E22 — switch off (KAN-116) |
| upsertSEOMetaAction | admin:seo.write | Zod `seoMetaSchema` (page; title ≤ 60; description ≤ 160; og*; twitterCard enum; canonical url; noindex; nofollow) | `{seoMeta}` | Unauth; Zod msg; msg | upserts `seo_meta`; audit `seo.upserted`. **UI** add-meta-dialog | E22 — switch off (KAN-116) |
| deleteSEOMetaAction | admin:seo.delete | `page` | `{message}` | Unauth; msg | deletes; audit `seo.deleted` | E22 — switch off (KAN-116) |
| getAllURLRedirectsAction | admin:seo.read | — | `{redirects[]}` | Unauth; msg | reads `url_redirects` | E22 — switch off (KAN-116) |
| createURLRedirectAction | admin:seo.write | Zod `urlRedirectSchema` (fromPath, toPath, statusCode `'301'\|'302'`→number, enabled?) | `{redirect}` | Unauth; Zod msg; msg | creates `url_redirects` from the raw `data`, so `statusCode` stays a string ⚠; audit `redirect.created`. **UI** add-redirect-dialog | E22 — switch off (KAN-116) |
| updateURLRedirectAction | admin:seo.write | `id`, same schema | `{redirect}` | Unauth; Zod msg; msg | updates; audit `redirect.updated` | E22 — switch off (KAN-116) |
| deleteURLRedirectAction | admin:seo.delete | `id` | `{message}` | Unauth; msg | deletes; audit `redirect.deleted` | E22 — switch off (KAN-116) |
| toggleURLRedirectAction | admin:seo.write | `id` | `{redirect}` | Unauth; `'Redirect not found'`; msg | flips `enabled`; **no audit** | E22 — switch off (KAN-116) |
| getActiveRedirectAction | **none** | `fromPath` | `{redirect}` | `'No active redirect found'`; msg | reads `url_redirects`. Unused | E22 — switch off (KAN-116) |
| bulkImportSEOMetaAction | admin:seo.write | `seoMeta[]` (each Zod-checked) | `{message, successCount, errorCount, errors?}` | Unauth; msg | upserts many; audit `seo.bulk_import` | E22 — switch off (KAN-116) |

## src/app/actions/admin/settings-actions.ts (17)

Auth is `admin:settings.*`, except where marked.

| Action | Auth | Inputs | Output | Errors | Side effects | Porting story |
|---|---|---|---|---|---|---|
| getAllAppSettingsAction | admin:settings.read | `category?` | `{settings[]}` | Unauth; msg | reads `app_settings` | E22 — switch off (KAN-118) |
| getAppSettingByKeyAction | admin:settings.read | `key` | `{setting}` | Unauth; `'Setting not found'`; msg | reads | E22 — switch off (KAN-118) |
| upsertAppSettingAction | admin:settings.write | Zod `appSettingSchema` (key, `value: any`, category, description?) | `{setting}` | Unauth; Zod msg; msg | upserts `app_settings`; audit `settings.upserted`; `revalidateTag('active-theme'\|'active-font')`. **UI** general and theme settings forms | E22 — switch off (KAN-118) |
| deleteAppSettingAction | admin:settings.delete | `key` | `{message}` | Unauth; msg | deletes; audit `settings.deleted` | E22 — switch off (KAN-118) |
| getSettingsByCategoryAction | admin:settings.read | `category` | `{settings[]}` | Unauth; msg | reads | E22 — switch off (KAN-118) |
| getAllFeatureFlagsAction | admin:settings.read | — | `{featureFlags[]}` | Unauth; msg | reads `feature_flags` | E22 — switch off (KAN-118) |
| getFeatureFlagByNameAction | **none** ⚠ | `name` | `{featureFlag}` | `'Feature flag not found'`; msg | reads. Unused | E22 — switch off (KAN-118) |
| upsertFeatureFlagAction | admin:settings.write | Zod `featureFlagSchema` (name, enabled, description?, rolloutPercentage 0–100) | `{featureFlag}` | Unauth; Zod msg; msg | upserts; audit `feature_flag.upserted` | E22 — switch off (KAN-118) |
| toggleFeatureFlagAction | admin:settings.write | `name` | `{featureFlag}` | Unauth; `'Feature flag not found'`; msg | flips `enabled`; audit `feature_flag.toggled`. **UI** feature-flags-list | E22 — switch off (KAN-118) |
| deleteFeatureFlagAction | admin:settings.delete | `name` | `{message}` | Unauth; msg | deletes; audit `feature_flag.deleted` | E22 — switch off (KAN-118) |
| getAllEmailTemplatesAction | admin:settings.read | — | `{templates[]}` | Unauth; msg | reads `email_templates` | E22 — switch off (KAN-117) |
| getEmailTemplateByNameAction | admin:settings.read | `name` | `{template}` | Unauth; `'Email template not found'`; msg | reads | E22 — switch off (KAN-117) |
| upsertEmailTemplateAction | admin:settings.write | Zod `emailTemplateSchema` (name, subject, htmlBody (raw HTML), textBody?, variables?) | `{template}` | Unauth; Zod msg; msg | upserts; audit `email_template.upserted`. No email is ever sent from these templates | E22 — switch off (KAN-117) |
| deleteEmailTemplateAction | admin:settings.delete | `name` | `{message}` | Unauth; msg | deletes; audit `email_template.deleted` | E22 — switch off (KAN-117) |
| getAuditLogsAction | admin:**settings.read** | `page = 1, limit = 50, filters?: {action? (contains), resource?, userId?}` | `{logs[], pagination}` | Unauth; msg | reads `audit_logs` | KAN-49 (tenant-aware, filter by org, store, user and action) |
| getSystemStatsAction | admin:settings.read | — | `{totalUsers, totalSettings, totalFeatureFlags, totalEmailTemplates, totalSEOMeta, totalRedirects, totalAuditLogs}` | Unauth; msg | counts | E22 — switch off (KAN-119) |
| bulkUpdateSettingsAction | admin:settings.write | `appSetting[]` (each Zod-checked) | `{message, successCount, errorCount, errors?}` | Unauth; msg | upserts many; audit `settings.bulk_update`; does **not** bust the theme or font cache | E22 — switch off (KAN-118) |

---

## API routes (src/app/api/**/route.ts) — 3 files, 4 handlers (6 files, 10 handlers before KAN-122)

| Route | Auth | Inputs | Output | Errors | Side effects | Porting story |
|---|---|---|---|---|---|---|
| `GET /api/auth/clear-session` | none | — | 307 redirect to `/login` | — | Deletes cookies `session` and `email-verified`. Used by the dashboard layout and page when a session is invalid. No Prisma | KAN-41 (keep as a frontend cookie helper, or replace with KAN-37 `DELETE /v1/auth/session`) |
| ~~`POST /api/auth/login` (+ `OPTIONS`, CORS `*`)~~ (removed, KAN-122) | Firebase ID token in the body | `{idToken}` (Zod `loginSchema`) | 200 `{success, user:{id, email, emailVerified, displayName, avatarUrl, subscriptionTier, subscriptionStatus, isAdmin}}` | 400 `'Invalid request'` + details; 401 `'Invalid or expired token'`; 400 `'Email not found in token'`; 500 `'Internal server error'` | Creates or updates `users`; creates `user_settings`; audit `user.created`; `login_history`; audit `user.login_failed` on error. Sets cookie **`auth-token` = the raw ID token** (7 days), which nothing else reads. Not called by the app | KAN-37 (`POST /v1/auth/session`). ✅ Route deleted (KAN-122, PR #4) |
| ~~`POST /api/auth/logout` (+ `OPTIONS`, CORS `*`)~~ (removed, KAN-122) | Bearer ID token or `session` cookie (unverified ok) | — | 200 `{success, message}` (always) | 500 `'Logout failed, but session cleared'` | Firebase `verifyIdToken`/`verifySessionCookie`, `revokeRefreshTokens`; audit `user.logout`; deletes cookies. Not called (logoutAction is used) | KAN-37 (`DELETE /v1/auth/session`). ✅ Route deleted (KAN-122, PR #4) |
| ~~`POST /api/auth/signup` (+ `OPTIONS`, CORS `*`)~~ (removed, KAN-122) | none | `{email, password (min 8), displayName? (min 2)}` (Zod `signupSchema`) | 201 `{success, message, user:{id, email, displayName, emailVerified}, customToken}` | 400 `'Invalid request'`; 409 `'User with this email already exists'`; 409 `'Email already registered in authentication system'`; 400 `'Password does not meet requirements'`; 500 `'Failed to create user account'`; 500 `'Internal server error'` | Firebase `createUser`, `createCustomToken`, and a compensating `deleteUser`; creates `users` and `user_settings`; audit `user.signup`; welcome `notifications` row. No rate limit; 409 reveals which emails exist. Not called | KAN-37 (client Firebase signup + session). ✅ Route deleted (KAN-122, PR #4). Welcome notification: KAN-40 |
| ~~`GET /api/test-logging`~~ (removed, KAN-146) | **none** | — | `{success, message, info, timestamp}` | 500 `'Logging test failed'` | Writes info, debug, warn and error log lines (and `console.log`). Test-only | Dead: delete (no port). At the latest in KAN-51 ✅ Route deleted (KAN-146, PR #20) |
| `POST /api/webhooks/stripe` (+ `OPTIONS`, CORS `*`) | Stripe signature (`stripe-signature` header, raw body) | Stripe `Event` | 200 `{received, eventId, eventType}` | 400 `'Missing signature header'`; 401 `'Invalid signature'`; **200** `{received, error:'Event processing failed', eventId}` when the handler fails (Stripe will not retry ⚠); 500 `'Webhook processing failed'` | `lib/stripe/webhooks.handleWebhookEvent` handles `checkout.session.completed`, `customer.subscription.created/updated/deleted`, `invoice.payment_succeeded/failed` and `customer.subscription.trial_will_end`. It updates `users`, writes `audit_logs`, creates `notifications` and calls `revalidatePath`. **No idempotency** | KAN-44 (raw-body signature check, process each event at most once, org status sync). **Removed in KAN-50**: the backend `POST /webhooks/stripe` is the only webhook |

---

## Pages querying Prisma directly

There are 12 page and layout files. The plan says "10 pages" because it counts the two layouts with their sections. All 12 must stop importing `@/lib/db/client` (security exit rule, KAN-50 AC: "None of the 10 pages that queried Prisma directly still does").

| File | Auth | What it queries | Porting / switch-off story |
|---|---|---|---|
| `(admin)/admin/layout.tsx` | session cookie (`checkRevoked`) plus an `admin_users` row; redirects to `/login` or `/dashboard` | `users` with `adminUser` (role for the header) | KAN-50 (call the API `me`/admin check), with KAN-46 `require_admin` |
| `(admin)/admin/page.tsx` | layout only | user counts (total, new, active, cancelled), 5 recent users, recent `audit_logs`, `groupBy` tier, pro and enterprise counts; `config/subscriptions` | KAN-50: recent users through KAN-47, recent logs through KAN-49. Stat cards: E22 — switch off (KAN-119) |
| `(admin)/admin/analytics/page.tsx` | layout only | user counts by period, subscription counts, `login_history` count, plan counts | E22 — switch off (KAN-119), done in KAN-50 |
| `(admin)/admin/audit-logs/page.tsx` | layout only | last 100 `audit_logs` | KAN-50 through KAN-49 |
| `(admin)/admin/seo/page.tsx` | layout only | `seo_meta`, `url_redirects` | E22 — switch off (KAN-116), done in KAN-50 |
| `(admin)/admin/settings/page.tsx` | layout only | `app_settings` (general, `active_theme`), `feature_flags`, `email_templates`; currency through `config/subscriptions` | E22 — switch off (KAN-118, KAN-117), done in KAN-50 |
| `(admin)/admin/subscriptions/page.tsx` | layout only | subscription counts by tier and status, cancelled this month, recent subscribers | KAN-50: list through KAN-48. Counts: E22 — switch off (KAN-119) |
| `(admin)/admin/users/page.tsx` | layout only | `users` search `?q=` (email/displayName, insensitive) with `adminUser`, take 50 | KAN-50 through KAN-47 |
| `(admin)/admin/users/[id]/page.tsx` | layout only | user plus `adminUser`, `settings`, 10 `login_history`, 10 `notifications` | KAN-50 through KAN-47. Notifications panel: E22 — switch off (KAN-40) |
| `dashboard/layout.tsx` | session cookie; on failure redirects to `/api/auth/clear-session` | `users` (displayName, avatar), unread `notifications` count, 10 recent notifications | KAN-41 / KAN-50 through KAN-38 `GET /v1/me`. Notifications dropdown: E22 — switch off (KAN-40) |
| `dashboard/page.tsx` | session cookie (same) | `users`; `notifications` total and unread; successful `login_history` count | KAN-50 through KAN-38. Notification stats: E22 — switch off (KAN-40) |
| `pricing/page.tsx` | optional session | `users.subscriptionTier`; `getSubscriptionPlans()` and `getCurrencySymbol()` (`app_settings[currency]` + Stripe prices) | KAN-45 (plans from KAN-42, current plan from KAN-43) |

## Shared server modules (other importers of `@/lib/db/client`)

| Module | Exports | Importers | Retired by |
|---|---|---|---|
| `src/lib/services/audit-log.service.ts` | `logAdminAction`, `getAuditLogs`, `cleanupOldAuditLogs` | **none (dead)** | Replaced by KAN-46/KAN-49 (backend audit logging); deleted in KAN-51 |
| `src/lib/stripe/subscriptions.ts` | `createCheckoutSession`, `createBillingPortalSession`, `updateSubscription`, `cancelSubscription`, `resumeSubscription`, `getSubscription`, `getSubscriptionTier`, `syncSubscriptionStatus` | `user-actions.deleteAccountAction`, `stripe/webhooks.ts` | KAN-43; **removed in KAN-50** |
| `src/lib/stripe/webhooks.ts` | `verifyWebhookSignature`, `handleWebhookEvent` | `api/webhooks/stripe` | KAN-44; **removed in KAN-50** |
| `src/lib/stripe/server.ts` (added in KAN-134) | `getStripeServerClient` (lazy server Stripe client; throws if `STRIPE_SECRET_KEY` is missing, at call time not at import) | `subscription-actions.ts`, `admin/subscription-actions.ts` | Does not import `db`, but holds a server secret. KAN-43/KAN-44 move Stripe to the backend; deleted in KAN-51 |
| `src/lib/stripe/client.ts` | `getStripe` (browser `loadStripe`, publishable key) | none in `src/` | Does not import `db`. Keep only if KAN-45 needs Stripe.js; otherwise delete in KAN-51 |
| `src/lib/utils/notifications.ts` | `createNotification`, `notifyPasswordChanged`, `notifyNewDeviceLogin`, `notifySubscriptionChanged`, `notifyEmailVerified`, `notifyPaymentFailed` | auth-actions, user-actions, stripe/webhooks | E22 — switch off (KAN-40); **removed in KAN-50** |
| `src/lib/helpers/admin-helpers.ts` | `requireAdmin`, `hasPermission`, `requirePermission`, `isAdmin`, `getCurrentAdmin` | **none (dead)** | KAN-46 (`require_admin(permissions)`); deleted in KAN-51 |
| `src/lib/middleware/admin-auth.ts` | `verifyAdminAuth` (Bearer ID token), `hasPermission`/`hasAny`/`hasAll`, `ADMIN_PERMISSIONS`, `ROLE_PERMISSIONS` | **none (dead)** | KAN-46 (port the permission catalogue); deleted in KAN-51 |
| `src/config/subscriptions.ts` | `SUBSCRIPTION_TIERS`, `subscriptionPlans`, `getStripePrices` (cached), `getSubscriptionPlans`, `getCurrencySymbol` (cached, `app_settings[currency]`) | pricing page and admin overview, analytics, settings and subscriptions pages | KAN-42 (plans and limits in the backend) + KAN-45. Currency setting: KAN-118 or hard-coded. Server parts removed in KAN-51 |

---

## ⚠ Notes

**Duplicates**
1. There are two sets of notification actions. notification-actions.ts has `getNotificationsAction`, `markNotificationAsReadAction`, `markAllNotificationsAsReadAction` and `deleteNotificationAction`. user-actions.ts has `getUserNotificationsAction`, `markNotificationReadAction`, `markAllNotificationsReadAction` and **`deleteNotificationAction`** (the same exported name in two modules). All of them are switched off in KAN-40.
2. `deleteUserAccountAction` is just an alias of `deleteAccountAction`. Port only `DELETE /v1/me`.
3. `getUserLoginHistoryAction` (returns `{loginHistory}`) duplicates `getLoginHistoryAction` (returns `{history}`, the one the UI uses).
4. ✅ **Resolved in KAN-122 (PR #4): the routes were removed.** The two auth paths overlapped: the routes `/api/auth/login|logout|signup` and the actions `verifyTokenAction` and `logoutAction`. The UI used only the actions. The login route set a different cookie (`auth-token` = raw ID token) that nothing read.
5. Admin auth is implemented four times: a `getAuthenticatedAdmin`/`hasPermission` copy in each admin action file, plus `admin-helpers.ts` and `admin-auth.ts` (both dead). The admin pages ignore permissions entirely. KAN-46 should be the single source.

**Dead or test-only**
6. ✅ **Resolved in KAN-146 (PR #20): removed.** `GET /api/test-logging` was unauthenticated and test-only.
7. 58 of the 92 actions (60 of 94 before KAN-122) are not called from the UI. All admin user and admin subscription actions, most SEO and settings actions, `loginAction`, `signUpAction`, `getCurrentSessionAction`, `verifyEmailAction`, `updateSubscriptionAction`, `getUpcomingInvoiceAction` and `hasActiveSubscriptionAction` are unused. The admin pages read Prisma directly instead. Port by behaviour (the story AC), not by action.
8. `loginAction`, `signUpAction` and `verifyEmailAction` are no-ops or misuse the client SDK. Delete them; they have no porting story.
9. `getUpcomingInvoiceAction` calls `invoices.retrieveUpcoming`, which the pinned API version `2025-08-27.basil` removed. It is probably broken.

**No clear porting story or ambiguous**
10. `changePasswordAction` is not named in the KAN-38 or KAN-41 AC. Decide between client-side Firebase `reauthenticate` + `updatePassword` (KAN-41) and a KAN-38 endpoint.
11. `updateUserSubscriptionAction` (manual tier/status edit) is not in the KAN-48 AC. Drop it, or fold it into grant-free.
12. `getActiveFont`/`getActiveTheme` and `config/subscriptions.getCurrencySymbol` read `app_settings`, which is cut (KAN-118). They are used by the root layout and pricing page, so switching off means hard-coded defaults until KAN-118. Confirm that this is acceptable.
13. `(admin)/admin/page.tsx` mixes kept data (recent users, logs) with cut stats (KAN-119). KAN-50 must split it.
14. Page count: the plan says 10 Prisma pages; the code has 12 files. The two layouts are the difference.

**Security, seen in passing (fix or make sure the port does not carry it over)**
15. ✅ **Fixed in KAN-122 (PR #4): action removed.** **Critical:** `requestPasswordResetAction` needs no auth and **returns the Firebase password-reset link to the caller**. Anyone who calls the server action with a victim's email can take over that account. It is unused, but exported server actions can be called directly. Remove it now or in KAN-41.
16. ✅ **Fixed in KAN-122 (PR #4): new users always start on free.** **High:** `verifyTokenAction` sets `subscriptionTier` on new users from the client-supplied `metadata.selectedPlan`, so a user can self-assign `enterprise` without paying.
17. ✅ **Fixed in KAN-122 (PR #4): action removed.** **High:** `syncUserAction` (no auth) upserts a `users` row for any `firebaseUid`.
18. **High:** `updateUserProfileAction` returns the full `users` row to the browser (`twoFactorSecret`, Stripe ids, `firebaseUid`). `getUserByIdAction` does the same for admins.
19. **High:** 2FA is never enforced at login. `verifyTokenAction` ignores `twoFactorEnabled`, so TOTP is cosmetic. The secret is stored in plaintext and returned at setup. KAN-39 must enforce it and encrypt the secret.
20. **High:** the email-verification gate in `proxy.ts` trusts the non-httpOnly, client-writable `email-verified` cookie.
21. **High:** `grantAdminRoleAction` lets any holder of `admins.create` grant `*` or `super_admin`, so admins can escalate privileges.
22. **Medium:** admin pages rely only on `(admin)/admin/layout.tsx` (admin row exists). There are no per-page checks and no permission granularity, so a `users.read`-only admin sees settings, SEO and audit logs.
23. **Medium:** `getFeatureFlagByNameAction` and `getActiveRedirectAction` have no auth (read-only).
24. **Medium:** Stripe-related:
    - `createCheckoutSessionAction` (success/cancel URL) and `createBillingPortalSessionAction` (`returnUrl`) accept any host, which is an open redirect.
    - `updateSubscriptionAction` accepts any `newPriceId`.
    - `refundSubscriptionPaymentAction` does not validate `amount`.
    - The webhook returns 200 on processing failure, so events are lost, and it has no idempotency (KAN-44).
25. **Medium:** every action returns raw `error.message` (Prisma, Stripe and Firebase internals) to the client. `/api/auth/signup` 409s and `requestPasswordResetAction` revealed which emails exist, and the auth routes sent `Access-Control-Allow-Origin: *` (all three removed in KAN-122). The Stripe webhook route still sends it. There is no rate limiting on signup, password change or 2FA verification.
26. **Low:**
    - `deleteAccountAction` needs no re-authentication and writes no audit log.
    - `updateUserAction` changes the email in the database but not in Firebase.
    - `createURLRedirectAction`/`updateURLRedirectAction` write the untransformed `statusCode` string.
    - `toggleURLRedirectAction` and `sendUserNotificationAction` write no audit log.
    - `getAuditLogsAction` is gated on `settings.read` instead of an audit permission.
    - `verifyUpgradeSessionAction` never checks the token value.
