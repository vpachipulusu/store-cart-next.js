# Subscription Upgrade E2E Tests

## Overview

Comprehensive end-to-end tests for the subscription upgrade functionality, covering the complete flow from initiating an upgrade to verifying the subscription status update.

## Test Files

### 1. `subscription.spec.ts` - Comprehensive Test Suite

Complete test coverage including:

- ✅ Unauthenticated user flow (redirect to signup)
- ✅ Authenticated user upgrade flow
- ✅ Stripe checkout integration
- ✅ Success redirect and webhook processing
- ✅ Subscription status polling
- ✅ Dashboard updates after upgrade
- ✅ Error handling (declined cards, insufficient funds)
- ✅ Checkout cancellation flow
- ✅ Multiple Stripe test card scenarios

### 2. `subscription-simple.spec.ts` - Happy Path Test

Focused test for the critical happy path:

- Login → Pricing → Upgrade → Checkout → Success → Verification

## Prerequisites

### 1. Environment Variables

Required in `.env.local`:

```env
# Test user credentials
TEST_USER_EMAIL=testuser@example.com
TEST_USER_PASSWORD=TestPass123!

# Stripe keys (test mode)
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Stripe price IDs
STRIPE_PRICE_ID_PRO_MONTHLY=price_...
STRIPE_PRICE_ID_PRO_YEARLY=price_...
STRIPE_PRICE_ID_ENTERPRISE_MONTHLY=price_...
STRIPE_PRICE_ID_ENTERPRISE_YEARLY=price_...
```

### 2. Test User Setup

Create a test user in your database with:

- Email: Value from `TEST_USER_EMAIL`
- Password: Value from `TEST_USER_PASSWORD`
- Subscription Tier: `free`
- Email Verified: `true`

You can use the signup flow or seed script to create this user.

### 3. Stripe Test Mode

- All tests use **Stripe test mode** with test API keys
- No real charges will be made
- Test cards are used for payment simulation

## Stripe Test Cards

The tests use official Stripe test cards:

| Card Number        | Scenario                               |
| ------------------ | -------------------------------------- |
| `4242424242424242` | ✅ Successful payment                  |
| `4000000000000002` | ❌ Card declined                       |
| `4000000000009995` | ❌ Insufficient funds                  |
| `4000000000000069` | ❌ Expired card                        |
| `4000002500003155` | 🔐 Requires authentication (3D Secure) |
| `4000000000000119` | ⚠️ Processing error                    |

See: https://stripe.com/docs/testing#cards

## Running the Tests

### Run All Subscription Tests

```bash
npm run test:e2e -- subscription
```

### Run Specific Test File

```bash
# Comprehensive tests
npm run test:e2e -- subscription.spec.ts

# Simple happy path only
npm run test:e2e -- subscription-simple.spec.ts
```

### Run in UI Mode (Debug)

```bash
npx playwright test subscription --ui
```

### Run in Headed Mode (See Browser)

```bash
npx playwright test subscription --headed
```

### Run Specific Browser

```bash
# Chrome only
npx playwright test subscription --project=chromium

# Firefox only
npx playwright test subscription --project=firefox

# Mobile Chrome
npx playwright test subscription --project=mobile-chrome
```

## Test Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ 1. User Login (Free Tier)                                  │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Navigate to Pricing Page                                │
│    • Verify all tiers displayed                            │
│    • Verify upgrade button visible                         │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Click "Upgrade to Pro"                                  │
│    • Server action creates checkout session                │
│    • Redirect to Stripe Checkout                           │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Stripe Checkout (New Window)                            │
│    • Fill test card: 4242 4242 4242 4242                   │
│    • Expiry: 12/34                                          │
│    • CVC: 123                                               │
│    • Submit payment                                         │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. Stripe Processes Payment                                │
│    • checkout.session.completed webhook fired               │
│    • Webhook handler updates database                      │
│    • subscriptionTier: free → pro                          │
│    • subscriptionStatus: active                            │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. Redirect to /dashboard?upgrade=success                  │
│    • Success banner shown                                   │
│    • SubscriptionSuccessHandler starts polling              │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 7. Subscription Status Polling                             │
│    • Poll every 3 seconds (max 10 times)                   │
│    • Check if tier != 'free' && status == 'active'         │
│    • Wait for webhook to complete                          │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 8. Success Confirmed                                       │
│    • Show "Subscription Activated!" message                 │
│    • Auto-refresh to /dashboard                            │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 9. Verification                                            │
│    ✅ Dashboard shows "Pro" tier                           │
│    ✅ Subscription status card shows "active"              │
│    ✅ Upgrade banner removed                               │
│    ✅ Pro features unlocked                                │
└─────────────────────────────────────────────────────────────┘
```

## What the Tests Verify

### 1. UI Elements

- ✅ Upgrade banner appears for free tier users
- ✅ Pricing page displays all tiers correctly
- ✅ Upgrade button is visible and clickable
- ✅ Success message appears after payment

### 2. Stripe Integration

- ✅ Checkout session created with correct price ID
- ✅ Stripe checkout page loads in new window
- ✅ Payment form accepts test card data
- ✅ Successful payment redirects back to app

### 3. Webhook Processing

- ✅ `checkout.session.completed` event handled
- ✅ User subscription tier updated in database **immediately**
- ✅ Subscription status set to 'active' **without admin action**
- ✅ Stripe customer ID and subscription ID stored
- ✅ Admin pages automatically revalidated

### 4. Success Handler

- ✅ Success banner displays with loading state
- ✅ Polling mechanism checks subscription status
- ✅ Success state shown when subscription activates
- ✅ Auto-refresh removes query parameter

### 5. Dashboard Updates

- ✅ Subscription tier displayed as "Pro"
- ✅ Subscription status displayed as "active"
- ✅ Upgrade banner removed after upgrade
- ✅ Current period end date shown (if applicable)

### 6. Admin Panel Integration

- ✅ Subscriptions appear in admin panel **immediately** after webhook
- ✅ No manual admin approval required
- ✅ Subscription stats updated automatically
- ✅ Recent subscriptions table shows new upgrades
- ✅ Refresh button available for manual updates
- ✅ Empty state shown when no subscriptions exist

### 7. Error Handling

- ✅ Declined card shows error message
- ✅ Insufficient funds shows error message
- ✅ Checkout cancellation redirects properly
- ✅ Expired card handling

## Troubleshooting

### Test User Already on Pro Tier

If the test user is already upgraded:

```bash
# Reset user to free tier in database
# Or create a new test user
```

### Stripe Webhook Not Firing

1. Check webhook secret is correct
2. Verify webhook endpoint is reachable
3. Use Stripe CLI for local testing:

```bash
stripe listen --forward-to localhost:3000/api/webhooks/stripe
```

### Timeout Errors

- Increase timeout in test if webhook processing is slow
- Check server logs for webhook errors
- Verify database connection is working

### Checkout Window Not Opening

- Check popup blocker settings
- Verify Stripe publishable key is correct
- Ensure test mode keys are being used

## Test Data Cleanup

After running tests, you may want to:

1. Reset test user subscription tier to `free`
2. Delete Stripe test subscriptions
3. Clear audit logs created during testing

## CI/CD Integration

These tests are configured to run in CI:

```yaml
# GitHub Actions example
- name: Run E2E Tests
  run: npm run test:e2e
  env:
    TEST_USER_EMAIL: ${{ secrets.TEST_USER_EMAIL }}
    TEST_USER_PASSWORD: ${{ secrets.TEST_USER_PASSWORD }}
    STRIPE_SECRET_KEY: ${{ secrets.STRIPE_TEST_SECRET_KEY }}
    STRIPE_WEBHOOK_SECRET: ${{ secrets.STRIPE_TEST_WEBHOOK_SECRET }}
```

## Related Files

- `/src/app/actions/subscription-actions.ts` - Server actions for subscriptions
- `/src/lib/stripe/webhooks.ts` - Webhook event handlers
- `/src/lib/stripe/subscriptions.ts` - Subscription utilities
- `/src/components/dashboard/subscription-success-handler.tsx` - Success polling component
- `/src/app/dashboard/page.tsx` - Dashboard with subscription display

## Contributing

When adding new subscription features:

1. Add corresponding E2E tests
2. Use Stripe test cards for payment scenarios
3. Verify webhook handling
4. Test error cases
5. Update this README

## Resources

- [Stripe Testing](https://stripe.com/docs/testing)
- [Playwright Docs](https://playwright.dev/)
- [Next.js Testing](https://nextjs.org/docs/testing)
