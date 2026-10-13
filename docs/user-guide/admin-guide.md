# Admin guide

**Who this is for:** StoreCart platform administrators (StoreCart staff) only.

Merchants don't need this page. If you are not a platform administrator and you try to open the
admin area, you are sent back to your dashboard. Organisation and store roles (owner, admin,
staff) are a different thing and are not covered here. See [What's coming](roadmap.md).

> **Status:** in this release the admin area is kept to a minimum: **users**, **subscriptions**
> and the **audit log**. Several other sections are still visible but are **being removed** for
> redesign. Most admin screens are **view-only** today; buttons that would change data may do
> nothing yet. Everything here **may change**.

## Open the admin area

1. Sign in with your administrator account. An account becomes an administrator only when an
   engineer grants it (the person must have signed up first). There is no admin sign-up screen.
2. Open `/admin` directly: add `/admin` to the end of the StoreCart site address. **There is no link
   to the admin area in the dashboard yet**, so bookmark it.
3. Use the left-hand menu to move between sections.

To leave, select **Back to Dashboard**. To sign out, select **Logout**.

## Sections at a glance

| Section | Status | What it is for |
|---|---|---|
| **Dashboard** | Available (partly being removed) | Recent sign-ups and recent audit log entries. |
| **Users** | Available, view-only | Find and inspect user accounts. |
| **Subscriptions** | Available, view-only | See paying customers and renewal dates. |
| **Audit Logs** | Available | See recent administrative actions and system events. |
| **Analytics** | Being removed | Platform statistics. |
| **SEO** | Being removed | Meta tags, redirects and sitemaps. |
| **Settings** | Being removed | App settings, theme, feature flags, email templates, pricing. |

## Admin dashboard

The **Admin Dashboard** shows:

- **Recent Users**: the latest registrations. Select **View All Users** for the full list.
- **Recent Activity**: the latest audit log entries. Select **View All Logs** for more.
- **Quick Actions**: shortcuts to Users, Subscriptions, Analytics and Settings.

The stat cards (**Total Users**, **New Users**, **Active Subscriptions**, **MRR**) and
**Subscription Breakdown** are **being removed**. Don't use them for reporting.

## Find and inspect a user

1. Select **Users** in the menu.
2. Type in **Search users by email or name...** to narrow the list.
3. In the **All Users** table, check the **Status** (**Verified** or **Unverified**),
   **Subscription**, **Role** and **Joined** date.
4. To see more, open the row's menu (**Open menu**) and select **View Details**.

The **User Details** page shows:

- the account's email, display name, verification status and **Member Since** date;
- **Plan**, status and **Current Period End**;
- **Admin Role**, if the person is an administrator;
- their preferences (**Theme**, **Language**, **Timezone**, **Email Notifications**);
- **Recent login activity**.

Select **Back to Users** to return.

> **Not working yet (may change):** **Edit User**, **Suspend User** and the **Export** button on the
> Users page are visible but don't do anything yet. Suspending and reactivating users, deleting
> users, and granting or removing admin roles are planned for this release. Until then, ask an
> engineer. The **Recent notifications** panel is **being removed**.

## Review subscriptions

1. Select **Subscriptions** in the menu.
2. **Recent Subscriptions** lists each customer with their email, **Plan**, **Status** and
   **Renewal Date**.

If there are none, you see **No Active Subscriptions**.

The summary cards (**Total Active**, **Pro Plans**, **Enterprise Plans**, **MRR**) are **being
removed**. The **Manage** button does nothing yet (**may change**). Planned actions include
viewing a customer's Stripe subscription and invoices and cancelling a subscription. For refunds,
use Stripe directly for now.

> **May change:** subscriptions are moving from individual users to **organisations**. This page
> will then list organisations instead of users.

## Audit logs

1. Select **Audit Logs** in the menu.
2. The table shows the last 100 entries, with **Timestamp**, **User ID**, **Action**, **Resource**
   and **IP Address**.

If there are none, you see **No audit logs found**.

> **May change:** the audit log is being rebuilt so you can filter by organisation, store, user and
> action.

## Sections being removed

These sections are still visible but are **being removed** from this release. Don't make changes
in them; changes may be lost or have no effect.

- **Analytics**: user growth, revenue and activity charts.
- **SEO**: **Meta Tags**, **Redirects** and **Sitemap** tabs. SEO and redirects will return later
  as per-store settings for merchants.
- **Settings**: **General**, **Theme**, **Feature Flags**, **Email Templates** and **Pricing**
  tabs. Email templates will return later per store. Plans and prices will be managed outside
  this screen.

See [What's coming](roadmap.md#removed-for-redesign).
