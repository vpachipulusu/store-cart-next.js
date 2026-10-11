# Plans and billing

**Who this is for:** the person who pays for StoreCart.

Payments are handled by Stripe, a secure payment provider. StoreCart never shows your full card
number; you only see the card brand and last four digits.

> **Status: may change.** Billing is moving from your personal account to your **organisation**,
> so that one subscription covers all of an organisation's stores. The steps below describe the
> screens you see today. Plan names, prices, features and screens **may change** before stores are
> launched.

## The plans

| Plan | Price | How you get it |
|---|---|---|
| **Free** | No charge | Every new account starts here. |
| **Pro** | Monthly or yearly | Paid through Stripe checkout. |
| **Enterprise** | Monthly or yearly | Paid plan. On the Pricing page today, **Contact Sales** sends you to the Contact page. |

The **Pricing** page shows current prices, and a **Monthly** / **Yearly** switch. Yearly billing
shows a "Save ...%" label when it costs less than paying monthly.

> **May change:** the feature lists on the Pricing page (projects, storage, analytics and so on)
> are placeholders from an earlier version of the product. They will be replaced with StoreCart's
> real plan limits, such as the number of stores. The "14-day free trial" message on the Pricing
> page is also not confirmed. Don't rely on either yet.

**Choosing a plan on the sign-up page does not upgrade you.** You always start on Free and upgrade
after signing in.

## Upgrade to a paid plan

1. Sign in and select **Billing** in the top bar.
2. Under **Current Plan**, select **Upgrade Plan**. The Pricing page opens.
3. Choose **Monthly** or **Yearly**.
4. On the **Pro** card, select **Upgrade to Pro**.
5. You are taken to Stripe's secure checkout. Enter your payment details and confirm.
6. You return to your dashboard. Wait a few seconds for "Subscription Activated!".

If you leave checkout without paying, you return to the Pricing page and are not charged.

For **Enterprise**, select **Contact Sales** on the Enterprise card and send your request.
Enterprise checkout through Stripe **may change** to work the same way as Pro.

## See your current plan

1. Select **Billing** in the top bar.
2. **Current Plan** shows:
   - your plan and its status (for example **Active**);
   - whether you are **Billed monthly** or **Billed annually**;
   - the date it **Renews on**, or **Expires on** if you have cancelled.

## Change your plan

1. Select **Billing**, then **Change Plan**. The Pricing page opens and marks your
   **Current Plan**.
2. Choose what you want:
   - **Pro to Enterprise:** select **Contact Sales** on the Enterprise card.
   - **Back to Free:** select **Downgrade** on the Free card. This takes you back to Billing.
     Follow [Cancel your subscription](#cancel-your-subscription); you move to Free when your
     paid period ends.

> **May change:** switching directly between paid plans, or between monthly and yearly billing,
> from inside StoreCart is not available yet.

## Cancel your subscription

Cancelling stops your plan from renewing. You keep your paid features until the end of the period
you've already paid for.

1. Select **Billing** in the top bar.
2. Under **Auto-Renewal**, turn the switch **off**.
3. You see "Auto-renewal turned off. Your plan will expire at the end of the billing period."
4. **Current Plan** now shows **Cancels at period end** and the date it **Expires**.

## Resume your subscription

You can change your mind any time before the expiry date.

1. Select **Billing** in the top bar.
2. Under **Auto-Renewal**, turn the switch **on**.
3. You see "Auto-renewal turned on. Your subscription will renew automatically."

After your plan has expired, you can't resume it. [Upgrade](#upgrade-to-a-paid-plan) again
instead.

## Payment methods

**Payment Methods** on the Billing page lists your saved cards, for example
"Visa ending in 4242, Expires 08/2027". Your default card has a **Default** label.

### Add a card

1. Select **Add Payment Method**. You are taken to Stripe's secure billing page.
2. Add your card there, then return to StoreCart.

The **Add Payment Method** button only appears after you have paid for a plan at least once.

### Choose your default card

1. Next to the card, select **Set Default**.
2. You see "Default payment method updated".

### Remove a card

1. Next to the card, select **Remove**.
2. You see "Payment method removed".

You may not be able to remove a card while auto-renewal is on. Add another card and make it the
default first, or turn auto-renewal off.

## Invoices

**Billing History** lists your recent invoices with the amount, date and status (such as
**paid**).

- Select **PDF** to download an invoice.
- Select **View** to open it on Stripe's invoice page.

If you see "No invoices yet", you haven't been charged yet.

## If something goes wrong

- **"Failed to start checkout"**: try again. If it keeps happening, try again later.
- **Plan still shows Free after paying**: wait a minute and refresh the dashboard. Payments can
  take a few seconds to confirm.
