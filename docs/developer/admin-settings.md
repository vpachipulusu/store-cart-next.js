# Admin settings

**Last updated:** 2026-10-12
**Scope:** the admin settings area on `main` (`/admin/settings`). Moved from `nextjs-frontend/ADMIN_SETTINGS_GUIDE.md` in KAN-146. The "Next steps" are ideas, not planned work, and the area is old boilerplate that the backend migration will replace (its Prisma models are gone, KAN-51).

## Overview

This page describes the admin settings functionality, including currency and language configuration from the admin portal.

## Features

### 1. General Settings

The admin portal now includes a **General Settings** form with the following configurable options:

#### Currency Settings

- **9 Supported Currencies:**
  - USD ($) - US Dollar
  - EUR (€) - Euro
  - GBP (£) - British Pound
  - JPY (¥) - Japanese Yen
  - AUD (A$) - Australian Dollar
  - CAD (C$) - Canadian Dollar
  - CHF (Fr) - Swiss Franc
  - CNY (¥) - Chinese Yuan
  - INR (₹) - Indian Rupee

#### Language Settings

- **11 Supported Languages:**
  - English (en)
  - Spanish (es)
  - French (fr)
  - German (de)
  - Italian (it)
  - Portuguese (pt)
  - Japanese (ja)
  - Chinese (zh)
  - Korean (ko)
  - Arabic (ar)
  - Hindi (hi)

#### Other Settings

- **App Name**: Customize the application name
- **Support Email**: Set the primary support contact email
- **Default Timezone**: Configure the default timezone (currently UTC)

### 2. Feature Flags

Interactive feature flag management with toggle switches:

- Enable/disable features across the platform
- Real-time updates with optimistic UI
- Success/error toast notifications
- Audit logging for all changes

## File Structure

### Components Created

#### 1. GeneralSettingsForm Component

**Path**: `src/components/admin/general-settings-form.tsx`

**Purpose**: Client-side form for managing general app settings

**Key Features**:

- Select components for currency and language
- Input fields for app name, support email, and timezone
- Saves to `AppSettings` table via `upsertAppSettingAction`
- Toast notifications for success/error states

#### 2. FeatureFlagsList Component

**Path**: `src/components/admin/feature-flags-list.tsx`

**Purpose**: Interactive list for toggling feature flags

**Key Features**:

- Switch toggles for each feature flag
- Optimistic UI updates
- Server action integration with `toggleFeatureFlagAction`
- Disabled state during updates
- Visual badges for enabled flags

### Server Actions

**Path**: `src/app/actions/admin/settings-actions.ts`

**Key Functions**:

- `upsertAppSettingAction`: Create/update app settings
- `toggleFeatureFlagAction`: Toggle feature flag enabled state
- `getAllAppSettingsAction`: Fetch all settings by category
- `getAllFeatureFlagsAction`: Fetch all feature flags

All actions include:

- Admin authentication verification
- Permission checking (`settings.write`, `settings.read`)
- Audit logging
- Error handling

### Admin Settings Page

**Path**: `src/app/(admin)/admin/settings/page.tsx`

**Structure**: Tabbed interface with 5 sections:

1. **General**: App configuration (name, email, timezone, currency, language)
2. **Theme**: Theme settings (`theme-settings-form.tsx`)
3. **Feature Flags**: Feature flag toggles
4. **Email Templates**: Email template management
5. **Pricing**: Pricing configuration

## Data storage

The `AppSettings` and `FeatureFlag` tables were Prisma models. They were removed with Prisma (KAN-51), together with the `db:push` and `db:seed:settings` scripts; the backend settings API replaces them (see [backend-public-settings.md](backend-public-settings.md)).

## Setup Instructions

### 1. Access Admin Settings

1. Sign in as an admin user. An existing admin grants admin rights to another user through `POST /v1/admin/users/{user_id}/admin`; the first admin is granted in the backend database (see [local-e2e.md](local-e2e.md))
2. Navigate to `/admin/settings`
3. Configure currency and language from the "General" tab
4. Toggle feature flags from the "Feature Flags" tab

## Usage Examples

### Updating Currency

```typescript
// Admin can select from dropdown in UI
// Or programmatically:
await upsertAppSettingAction({
  key: 'currency',
  value: 'EUR',
  category: 'general',
  description: 'Default currency for pricing and billing',
});
```

### Updating Language

```typescript
await upsertAppSettingAction({
  key: 'language',
  value: 'es',
  category: 'general',
  description: 'Default language for the application interface',
});
```

### Toggling Feature Flags

```typescript
// Toggle via admin UI or programmatically:
await toggleFeatureFlagAction('oauth_signup');
```

## Ideas for later

### 1. Global Currency Application

Apply the saved currency setting to pricing pages:

- Read currency from `AppSettings` in pricing components
- Format prices using the selected currency symbol
- Update Stripe integration to use selected currency

### 2. Global Language Application

Apply the saved language setting throughout the app:

- Set up i18n/internationalization
- Load language files based on selected language
- Update UI text dynamically

### 3. Feature Flag Implementation

Use feature flags to conditionally render features:

```typescript
// Example: Check if OAuth signup is enabled
const flags = await db.featureFlag.findUnique({
  where: { name: 'oauth_signup' },
});

if (flags?.enabled) {
  // Show OAuth buttons
}
```

### 4. Currency Formatting Helper

Create a utility function to format prices:

```typescript
// src/lib/utils/format-currency.ts
import { db } from '@/lib/db/client';

export async function formatCurrency(amount: number): Promise<string> {
  const currencySetting = await db.appSettings.findUnique({
    where: { key: 'currency' },
  });

  const currency = (currencySetting?.value as string) || 'USD';

  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency,
  }).format(amount);
}
```

## Security Considerations

1. **Admin-Only Access**: All settings actions require admin authentication
2. **Permission-Based**: Actions check for specific permissions (e.g., `settings.write`)
3. **Audit Logging**: All changes are logged in the `AuditLog` table
4. **Validation**: Input validation using Zod schemas

## Testing

### Manual Testing Checklist

- [ ] Access `/admin/settings` as admin user
- [ ] Change currency from USD to EUR
- [ ] Verify setting persists on page reload
- [ ] Change language from English to Spanish
- [ ] Verify setting persists on page reload
- [ ] Toggle feature flag on/off
- [ ] Verify toast notifications appear
- [ ] Check audit logs for all changes
- [ ] Test as non-admin user (should be denied access)

### Automated Testing

Create integration tests for:

- Settings CRUD operations
- Feature flag toggles
- Permission validation
- Audit log creation

## Troubleshooting

### Settings Not Saving

1. Check browser console for errors
2. Verify admin user has `settings.write` permission
3. Check database connection
4. Review server action error responses

### Feature Flags Not Toggling

1. Verify `toggleFeatureFlagAction` is imported correctly
2. Check network tab for failed requests
3. Ensure feature flag exists in database
4. Verify admin permissions

### Currency/Language Not Applied Globally

1. Implement global read functions for settings
2. Create utility functions to format currency
3. Set up i18n for language support

## API Reference

### Server Actions

#### `upsertAppSettingAction(data)`

Creates or updates an app setting.

**Parameters**:

```typescript
{
  key: string;
  value: any;
  category: string;
  description?: string;
}
```

**Returns**: `Promise<AdminSettingsActionResponse>`

#### `toggleFeatureFlagAction(name)`

Toggles a feature flag's enabled state.

**Parameters**: `name: string`

**Returns**: `Promise<AdminSettingsActionResponse>`

#### `getAllAppSettingsAction(category?)`

Fetches all app settings, optionally filtered by category.

**Parameters**: `category?: string`

**Returns**: `Promise<AdminSettingsActionResponse>`

#### `getAllFeatureFlagsAction()`

Fetches all feature flags.

**Returns**: `Promise<AdminSettingsActionResponse>`
