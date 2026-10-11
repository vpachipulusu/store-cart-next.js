# Quick Start: Subscription E2E Tests

## 1. Setup Test Environment

### Configure Environment Variables

Add to `.env.local`:

```bash
# Test User Credentials
TEST_USER_EMAIL=testuser@example.com
TEST_USER_PASSWORD=TestPass123!

# Stripe Test Keys
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_test_your_key_here
STRIPE_SECRET_KEY=sk_test_your_key_here
STRIPE_WEBHOOK_SECRET=whsec_your_secret_here

# Stripe Price IDs (create in Stripe Dashboard > Products)
STRIPE_PRICE_ID_PRO_MONTHLY=price_your_id_here
STRIPE_PRICE_ID_PRO_YEARLY=price_your_id_here
STRIPE_PRICE_ID_ENTERPRISE_MONTHLY=price_your_id_here
STRIPE_PRICE_ID_ENTERPRISE_YEARLY=price_your_id_here
```

### Create Test User

```bash
npm run test:setup
```

This creates a test user with:

- Email: `testuser@example.com`
- Password: `TestPass123!`
- Tier: `free`
- Email Verified: `true`

## 2. Run Tests

### Run All Subscription Tests

```bash
npm run test:e2e:subscription
```

### Run in UI Mode (Recommended for Development)

```bash
npm run test:e2e:ui
```

Then select `subscription.spec.ts` or `subscription-simple.spec.ts`

### Run Specific Test

```bash
# Happy path only
npx playwright test subscription-simple

# All scenarios
npx playwright test subscription

# In headed mode (see browser)
npx playwright test subscription --headed

# Debug mode
npx playwright test subscription --debug
```

## 3. Reset Test User After Tests

If tests upgraded the user to Pro, reset back to free tier:

```bash
npm run test:reset
```

## 4. What Gets Tested

✅ **Full Upgrade Flow**

- Login as free tier user
- Navigate to pricing page
- Click "Upgrade to Pro"
- Complete Stripe checkout with test card
- Verify success redirect
- Verify webhook processing **immediately updates database**
- Verify subscription updated **without admin action**
- Verify dashboard shows Pro tier

✅ **Admin Panel Verification**

- Subscriptions appear in admin panel immediately
- No manual approval required
- Stats updated automatically via webhook
- Refresh button for manual updates
- Empty state when no subscriptions

✅ **Error Scenarios**

- Declined card handling
- Insufficient funds handling
- Expired card handling
- Checkout cancellation

✅ **UI Updates**

- Success banner display
- Subscription status polling
- Auto-refresh after success
- Upgrade banner removal

## 5. Stripe Test Cards

Use these test card numbers:

| Card                  | Scenario              |
| --------------------- | --------------------- |
| `4242 4242 4242 4242` | ✅ Success            |
| `4000 0000 0000 0002` | ❌ Declined           |
| `4000 0000 0000 9995` | ❌ Insufficient funds |

**Always use:**

- Expiry: Any future date (e.g., `12/34`)
- CVC: Any 3 digits (e.g., `123`)
- ZIP: Any 5 digits (e.g., `12345`)

## 6. Viewing Test Results

After running tests:

```bash
# Open HTML report
npx playwright show-report
```

Or check `playwright-report/index.html` in your browser.

## 7. Troubleshooting

**Test user already on Pro tier?**

```bash
npm run test:reset
```

**Webhook not firing?**

- Check `STRIPE_WEBHOOK_SECRET` is correct
- For local testing, use Stripe CLI:

```bash
stripe listen --forward-to localhost:3000/api/webhooks/stripe
```

**Timeout errors?**

- Ensure dev server is running: `npm run dev`
- Check database connection
- Review server logs for errors

**Tests skipped?**

- Verify environment variables are set
- Check test user exists: `npm run test:setup`

## 8. CI/CD Integration

Example GitHub Actions workflow:

```yaml
name: E2E Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup Node
        uses: actions/setup-node@v3
        with:
          node-version: '18'

      - name: Install dependencies
        run: npm ci

      - name: Install Playwright
        run: npx playwright install --with-deps

      - name: Setup test user
        run: npm run test:setup
        env:
          TEST_USER_EMAIL: ${{ secrets.TEST_USER_EMAIL }}
          TEST_USER_PASSWORD: ${{ secrets.TEST_USER_PASSWORD }}

      - name: Run E2E tests
        run: npm run test:e2e:subscription
        env:
          STRIPE_SECRET_KEY: ${{ secrets.STRIPE_TEST_SECRET_KEY }}
          STRIPE_WEBHOOK_SECRET: ${{ secrets.STRIPE_TEST_WEBHOOK_SECRET }}

      - uses: actions/upload-artifact@v3
        if: always()
        with:
          name: playwright-report
          path: playwright-report/
```

## 9. Next Steps

- Review [SUBSCRIPTION_TESTS.md](./src/__tests__/e2e/SUBSCRIPTION_TESTS.md) for detailed documentation
- Check test files in `src/__tests__/e2e/subscription*.spec.ts`
- Customize test scenarios for your specific needs
- Add tests for additional subscription features

## Quick Commands Reference

```bash
# Setup
npm run test:setup          # Create test user
npm run test:reset          # Reset to free tier

# Run Tests
npm run test:e2e:subscription  # Run subscription tests
npm run test:e2e:ui           # Interactive UI mode
npm run test:e2e -- --headed  # See browser

# Debug
npx playwright test subscription --debug
npx playwright show-report

# Development
npm run dev                   # Start dev server (required)
stripe listen --forward-to localhost:3000/api/webhooks/stripe  # Local webhook testing
```
