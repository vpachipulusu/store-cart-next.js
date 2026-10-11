# SaaS Boilerplate - Complete Guide

## Table of Contents

1. [Quick Start](#quick-start)
2. [Setup & Configuration](#setup--configuration)
3. [Development](#development)
4. [Features & Architecture](#features--architecture)
5. [Authentication & Authorization](#authentication--authorization)
6. [Admin Portal](#admin-portal)
7. [Subscription & Billing](#subscription--billing)
8. [Testing](#testing)
9. [Deployment](#deployment)
10. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Prerequisites

- Node.js 20+
- npm (comes with Node.js)
- PostgreSQL database
- Firebase project
- Stripe account

### Installation

```bash
# Install dependencies
npm install

# Copy environment file
cp .env.example .env

# Configure your environment variables (see Setup section)

# Initialize database
npx prisma generate
npx prisma db push

# Start development server
npm run dev
```

Visit `http://localhost:3000`

---

## Setup & Configuration

### 1. Database Setup

#### Option A: Cloud Database (Recommended)

Use a managed PostgreSQL service:

- **Neon** (https://neon.tech) - Serverless Postgres
- **Supabase** (https://supabase.com)
- **Railway** (https://railway.app)
- **Vercel Postgres** (https://vercel.com/storage/postgres)

#### Option B: Local PostgreSQL

```sql
CREATE DATABASE saas_db;
```

Update `.env`:

```
DATABASE_URL="postgresql://username:password@localhost:5432/saas_db"
```

### 2. Firebase Setup

1. Go to [Firebase Console](https://console.firebase.google.com)
2. Create a new project
3. Enable Authentication → Email/Password
4. Enable OAuth providers (Google, GitHub)
5. Go to Project Settings → Service Accounts
6. Generate new private key (save as `firebase-service-account.json`)
7. Go to Project Settings → General → Your apps → Web app
8. Copy configuration to `.env`:

```env
NEXT_PUBLIC_FIREBASE_API_KEY="your-api-key"
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN="your-project.firebaseapp.com"
NEXT_PUBLIC_FIREBASE_PROJECT_ID="your-project-id"
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET="your-project.appspot.com"
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID="123456789"
NEXT_PUBLIC_FIREBASE_APP_ID="1:123456789:web:abc123"

# Service account (from JSON file)
FIREBASE_PROJECT_ID="your-project-id"
FIREBASE_CLIENT_EMAIL="firebase-adminsdk-xxxxx@your-project.iam.gserviceaccount.com"
FIREBASE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
```

### 3. Stripe Setup

1. Go to [Stripe Dashboard](https://dashboard.stripe.com)
2. Get API keys from Developers → API keys
3. Create products and prices
4. Set up webhook endpoint

```env
STRIPE_SECRET_KEY="sk_test_..."
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY="pk_test_..."
STRIPE_WEBHOOK_SECRET="whsec_..."

# Price IDs (create in Stripe Dashboard)
STRIPE_PRICE_ID_PRO_MONTHLY="price_..."
STRIPE_PRICE_ID_PRO_YEARLY="price_..."
STRIPE_PRICE_ID_ENTERPRISE_MONTHLY="price_..."
STRIPE_PRICE_ID_ENTERPRISE_YEARLY="price_..."
```

### 4. Database Initialization

```bash
# Generate Prisma Client
npx prisma generate

# Create database tables
npx prisma db push

# (Optional) Seed database
npx prisma db seed
```

### 5. Create Admin User

```bash
node scripts/create-admin.mjs
```

Follow the prompts to create your first admin user.

---

## Development

### Starting Development Server

```bash
npm run dev              # Start with automatic cleanup
npm run dev:clean        # Explicit clean and start
```

### Common Commands

```bash
npm run dev              # Start development server
npm run build            # Build for production
npm run start            # Start production server
npm run lint             # Run ESLint
npm run test             # Run all tests
npm run test:unit        # Run unit tests (Vitest)
npm run test:e2e         # Run E2E tests (Playwright)
npm run prisma:studio    # Open Prisma Studio
npm run prisma:generate  # Generate Prisma Client
```

### Project Structure

```
src/
├── app/
│   ├── (auth)/              # Authentication pages
│   │   ├── login/           # Login page
│   │   ├── signup/          # Signup with plan selection
│   │   ├── reset-password/  # Password reset
│   │   └── verify-email/    # Email verification
│   ├── (admin)/             # Admin portal
│   │   └── admin/           # Admin routes
│   │       ├── page.tsx     # Admin dashboard
│   │       ├── users/       # User management
│   │       ├── subscriptions/ # Subscription management
│   │       ├── analytics/   # Analytics dashboard
│   │       ├── seo/         # SEO management
│   │       ├── settings/    # App settings
│   │       └── audit-logs/  # Audit logs
│   ├── dashboard/           # Customer dashboard
│   │   ├── page.tsx         # Dashboard home
│   │   ├── profile/         # User profile
│   │   ├── settings/        # User settings
│   │   └── security/        # Security settings
│   ├── pricing/             # Pricing page (smart CTAs)
│   ├── contact/             # Contact form
│   ├── actions/             # Server Actions
│   │   ├── auth-actions.ts
│   │   ├── user-actions.ts
│   │   ├── subscription-actions.ts
│   │   └── admin/
│   ├── api/                 # API Routes
│   │   ├── auth/
│   │   └── webhooks/
│   └── page.tsx             # Landing page
├── components/
│   ├── ui/                  # shadcn/ui components
│   ├── auth/                # Auth forms
│   ├── pricing/             # Pricing components
│   └── providers/           # React providers
├── lib/
│   ├── db/                  # Database client
│   ├── firebase/            # Firebase setup
│   ├── stripe/              # Stripe integration
│   ├── middleware/          # Middleware functions
│   ├── services/            # Service layer
│   └── utils/               # Utilities
├── config/                  # Configuration
├── hooks/                   # Custom hooks
└── proxy.ts                 # Middleware (Next.js 16+)
```

---

## Features & Architecture

### Tech Stack

**Frontend:**

- Next.js 16 (App Router)
- React 19 (Server & Client Components)
- TypeScript
- Tailwind CSS v4
- shadcn/ui + Radix UI
- TanStack Query v5

**Backend:**

- Next.js API Routes & Server Actions
- Prisma ORM v6
- PostgreSQL
- Firebase Admin SDK
- Stripe

**Testing:**

- Vitest (unit & integration)
- Playwright (E2E)
- React Testing Library

### Core Features

#### Customer Dashboard (`/dashboard`)

- **Stats Cards**: Account status, subscription, notifications, login count
- **Quick Actions**: Profile, Settings, Security, Billing
- **Recent Activity**: Login history with IP and location
- **Notifications**: Unread notifications feed
- **Account Summary**: Account age, login stats

#### Profile Management (`/dashboard/profile`)

- Edit display name, bio, location, website, phone
- Avatar upload
- Form validation with Zod
- Real-time updates

#### Settings (`/dashboard/settings`)

- Theme selection (Light/Dark/System)
- Email notifications toggle
- Language and timezone preferences
- Auto-save functionality

#### Security (`/dashboard/security`)

- Password change
- Two-factor authentication (coming soon)
- Login history table
- Data export (JSON)
- Account deletion with confirmation

---

## Authentication & Authorization

### Firebase Authentication

The app uses Firebase for authentication with email/password and OAuth providers.

#### Auth Flow

1. **Signup**: User registers → Firebase creates auth user → Database user created with selected plan
2. **Login**: User signs in → Session cookie created → Login history recorded
3. **Session**: Server-side session verification via Firebase Admin SDK
4. **Logout**: Session cookie cleared → Refresh tokens revoked

#### Protected Routes

Routes are protected via `proxy.ts` middleware:

- `/dashboard/*` - Requires authentication
- `/settings/*` - Requires authentication
- `/profile/*` - Requires authentication
- `/security/*` - Requires authentication
- `/admin/*` - Requires authentication + admin role

#### Email Verification

- Users must verify email to access protected routes
- Verification status stored in cookie
- Automatic redirect to `/verify-email` if not verified

### Login History Tracking

Every successful login is recorded with:

- IP address (from headers)
- User agent (browser/device info)
- Geographic location (via IP lookup)
- Timestamp
- Success/failure status

### Server Actions

**Auth Actions** (`src/app/actions/auth-actions.ts`):

- `verifyTokenAction(idToken, metadata)` - Verifies ID token, creates/updates user, records login
- `loginAction(email, password)` - Validates login credentials
- `signUpAction(email, password, displayName)` - Validates signup
- `logoutAction()` - Clears session
- `requestPasswordResetAction(email)` - Initiates password reset

**User Actions** (`src/app/actions/user-actions.ts`):

- `getUserProfileAction()` - Get user profile
- `updateUserProfileAction(data)` - Update profile
- `getUserSettingsAction()` - Get settings
- `updateUserSettingsAction(data)` - Update settings
- `changePasswordAction(currentPassword, newPassword)` - Change password
- `getLoginHistoryAction(page, limit)` - Get login history
- `exportUserDataAction()` - Export all user data
- `deleteAccountAction(confirmText)` - Delete account

---

## Admin Portal

### Access & Authentication

Admin portal is accessible at `/admin` and requires:

1. Valid authentication session
2. AdminUser record in database

### Creating Admin Users

```bash
node scripts/create-admin.mjs
```

Or manually add to database:

```sql
INSERT INTO admin_users (id, user_id, role, permissions, created_at, updated_at)
VALUES (gen_random_uuid(), 'user-id-here', 'superadmin', '["all"]', NOW(), NOW());
```

### Admin Features

#### Dashboard (`/admin`)

- Total users with 30-day growth
- Active subscriptions count
- Monthly Recurring Revenue (MRR)
- New users (last 30 days)
- Subscription tier breakdown
- Recent user registrations
- Quick action links

#### User Management (`/admin/users`)

- User list with search
- Filter by tier, status, verification
- View user details
- Edit user information
- Delete users
- Export user data
- Pagination support

#### Subscription Management (`/admin/subscriptions`)

- Active subscriptions list
- Revenue metrics
- Subscription status filters
- Cancel/refund subscriptions
- View payment history
- Export subscription data

#### Analytics Dashboard (`/admin/analytics`)

- User growth charts
- Revenue trends
- Subscription distribution
- Churn rate
- Customer lifetime value
- Traffic sources
- Export analytics reports

#### SEO Management (`/admin/seo`)

- Meta tags management
- URL redirects (301/302)
- Edit SEO for pages
- Bulk operations
- Preview SEO tags

#### Settings (`/admin/settings`)

- App configuration
- Feature flags
- Email templates
- API keys management
- System settings

#### Audit Logs (`/admin/audit-logs`)

- All admin actions logged
- User activities tracked
- Filterable by action, user, date
- Export audit trail

### Audit Logging Service

All admin actions are automatically logged:

```typescript
import { logAuditAction } from '@/lib/services/audit-log.service';

await logAuditAction(userId, 'user.delete', {
  targetUserId: deletedUserId,
  email: user.email,
});
```

---

## Subscription & Billing

### Pricing Tiers

| Tier       | Price  | Features                                           |
| ---------- | ------ | -------------------------------------------------- |
| Free       | $0     | 3 projects, 1GB storage, basic features            |
| Pro        | $29/mo | Unlimited projects, 50GB storage, priority support |
| Enterprise | $99/mo | Custom everything, dedicated support               |

### Pricing Page Smart CTAs

The pricing page detects authentication state and shows appropriate CTAs:

**For Non-Authenticated Users:**

- Free: "Get Started" → `/signup`
- Pro: "Start Free Trial" → `/signup?plan=pro`
- Enterprise: "Contact Sales" → `/contact?plan=enterprise`

**For Authenticated Users:**

- Shows "Current Plan" for active tier (disabled)
- Shows "Upgrade to Pro" for free users → Stripe Checkout
- Shows "Upgrade to Enterprise" → Contact form

### Stripe Integration

#### Checkout Flow

1. User clicks "Upgrade to Pro" on pricing page
2. `createCheckoutSessionAction` creates Stripe session
3. User redirected to Stripe Checkout
4. After payment, Stripe webhook updates database
5. User redirected back to `/dashboard?upgrade=success`

#### Webhook Handling

Stripe webhooks are handled at `/api/webhooks/stripe`:

- `checkout.session.completed` - Creates subscription
- `invoice.payment_succeeded` - Updates payment status
- `customer.subscription.updated` - Updates subscription
- `customer.subscription.deleted` - Cancels subscription

#### Subscription Actions

```typescript
// Create checkout session
const result = await createCheckoutSessionAction(priceId, successUrl, cancelUrl);

// Get subscription status
const status = await getSubscriptionStatusAction();

// Cancel subscription
await cancelSubscriptionAction();

// Create billing portal session
const portal = await createBillingPortalSessionAction(returnUrl);
```

---

## Testing

### Unit Tests (Vitest)

```bash
npm run test:unit
```

Test files: `src/__tests__/unit/**/*.test.tsx`

Example:

```typescript
import { render, screen } from '@testing-library/react';
import { Button } from '@/components/ui/button';

test('Button renders correctly', () => {
  render(<Button>Click me</Button>);
  expect(screen.getByText('Click me')).toBeInTheDocument();
});
```

### E2E Tests (Playwright)

```bash
npm run test:e2e
```

Test files: `src/__tests__/e2e/**/*.spec.ts`

Example:

```typescript
import { test, expect } from '@playwright/test';

test('user can login', async ({ page }) => {
  await page.goto('/login');
  await page.fill('[name="email"]', 'test@example.com');
  await page.fill('[name="password"]', 'password123');
  await page.click('button[type="submit"]');
  await expect(page).toHaveURL('/dashboard');
});
```

### Test Coverage

```bash
npm run test:coverage
```

---

## Deployment

### Vercel Deployment

1. Push code to GitHub
2. Connect repository to Vercel
3. Add environment variables
4. Deploy

```bash
# Or use Vercel CLI
npm i -g vercel
vercel
```

### Environment Variables

Set these in Vercel dashboard:

```
DATABASE_URL
NEXT_PUBLIC_FIREBASE_API_KEY
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN
NEXT_PUBLIC_FIREBASE_PROJECT_ID
FIREBASE_PROJECT_ID
FIREBASE_CLIENT_EMAIL
FIREBASE_PRIVATE_KEY
STRIPE_SECRET_KEY
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY
STRIPE_WEBHOOK_SECRET
```

### Build Configuration

```json
{
  "buildCommand": "npx prisma generate && npm run build",
  "outputDirectory": ".next",
  "installCommand": "npm install",
  "devCommand": "npm run dev"
}
```

---

## Troubleshooting

### Lock File Error

**Problem:**

```
⨯ Unable to acquire lock at .next\dev\lock
```

**Solution:**

```bash
npm run dev:kill    # Kills processes and removes lock
npm run dev         # Start fresh
```

### Module Not Found: lucide-react

**Problem:**

```
Module not found: Can't resolve 'lucide-react'
```

**Solution:**
This project uses **npm** (not pnpm). Run:

```bash
rm -rf node_modules package-lock.json
npm install
```

### Database Connection Issues

**Problem:**

```
Can't reach database server
```

**Solutions:**

1. Check `DATABASE_URL` in `.env`
2. Ensure database is running
3. Verify network connectivity
4. Check firewall rules

### Firebase Authentication Errors

**Problem:**

```
Firebase: Error (auth/invalid-api-key)
```

**Solutions:**

1. Verify `.env` variables match Firebase Console
2. Check API key restrictions
3. Ensure Firebase Authentication is enabled
4. Verify authorized domains

### Stripe Webhook Failures

**Problem:**

```
Webhook signature verification failed
```

**Solutions:**

1. Check `STRIPE_WEBHOOK_SECRET` in `.env`
2. Use Stripe CLI for local testing:
   ```bash
   stripe listen --forward-to localhost:3000/api/webhooks/stripe
   ```
3. Verify webhook endpoint in Stripe Dashboard

### Prisma Schema Changes

After modifying `schema.prisma`:

```bash
npx prisma generate      # Regenerate client
npx prisma db push       # Push changes to database
# or
npx prisma migrate dev   # Create migration
```

### Authentication Loop Issue

If users get stuck in login/signup loop:

1. Check `proxy.ts` middleware
2. Verify session cookie is set
3. Clear browser cookies
4. Check Firebase session validity

### Admin Portal Access Denied

**Problem:**
Can't access `/admin` even when logged in

**Solution:**

1. Ensure user has `AdminUser` record:
   ```bash
   node scripts/create-admin.mjs
   ```
2. Check admin middleware logic
3. Verify session contains admin role

---

## Additional Resources

### Firebase Documentation

- [Firebase Auth](https://firebase.google.com/docs/auth)
- [Firebase Admin SDK](https://firebase.google.com/docs/admin/setup)

### Stripe Documentation

- [Stripe Checkout](https://stripe.com/docs/payments/checkout)
- [Webhooks](https://stripe.com/docs/webhooks)
- [Subscriptions](https://stripe.com/docs/billing/subscriptions/overview)

### Next.js Documentation

- [App Router](https://nextjs.org/docs/app)
- [Server Actions](https://nextjs.org/docs/app/building-your-application/data-fetching/server-actions-and-mutations)
- [Middleware](https://nextjs.org/docs/app/building-your-application/routing/middleware)

### Prisma Documentation

- [Prisma Client](https://www.prisma.io/docs/concepts/components/prisma-client)
- [Schema](https://www.prisma.io/docs/concepts/components/prisma-schema)
- [Migrations](https://www.prisma.io/docs/concepts/components/prisma-migrate)

---

## Support

For issues or questions:

1. Check this guide
2. Review GitHub issues
3. Check Next.js/Firebase/Stripe docs
4. Create new issue with reproduction steps
