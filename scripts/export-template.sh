#!/usr/bin/env bash
# Export the reusable template from StoreCart (KAN-145).
#
#   scripts/export-template.sh <target-dir> [ref]                 full export (default ref: HEAD)
#   scripts/export-template.sh <target-dir> <ref> --paths <p>...  copy only these paths (feature sync)
#
# Copies a clean `git archive` of <ref> into <target-dir>, removes every StoreCart-only path listed
# in docs/developer/template-export.md and scrubs the brand and Jira keys. The "trimmed" and
# "rewrite" files in that doc are edited by hand in the template repository afterwards; this
# script never edits the StoreCart checkout. With --paths it exports only the given paths (no
# deletions), which is how a `template-candidate` feature is pulled into the template later
# (docs/developer/template-export.md, "Build approach").
set -euo pipefail
shopt -s nullglob globstar

usage() { sed -n '2,10p' "$0"; exit 1; }

[ $# -ge 1 ] || usage
TARGET="$1"; shift
REF="HEAD"
PATHS=()
if [ $# -ge 1 ] && [ "$1" != "--paths" ]; then REF="$1"; shift; fi
if [ $# -ge 1 ]; then
  [ "$1" = "--paths" ] || usage
  shift
  PATHS=("$@")
  [ ${#PATHS[@]} -ge 1 ] || usage
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
git rev-parse --verify --quiet "$REF^{commit}" >/dev/null || { echo "unknown ref: $REF" >&2; exit 1; }

mkdir -p "$TARGET"
if [ ${#PATHS[@]} -eq 0 ] && [ -n "$(ls -A "$TARGET")" ]; then
  echo "target is not empty: $TARGET" >&2; exit 1
fi

echo "exporting $(git rev-parse --short "$REF") -> $TARGET"
git archive --format=tar "$REF" -- "${PATHS[@]}" | tar -x -C "$TARGET"

# ---------------------------------------------------------------- StoreCart-only paths
# Kept in step with docs/developer/template-export.md. Globs are resolved inside the target.
STORECART_ONLY=(
  # root
  .claude/plans .claude/PRPs .claude/progress .claude/skills .claude/CLAUDE.md
  .github/workflows/migrate-stores.yml .github/CODEOWNERS .github/ISSUE_TEMPLATE/story.md
  AGENTS.md PROJECT-CONTEXT.md README.md
  # docs
  docs/adr/0005-per-store-database-access.md docs/adr/0009-email-with-resend.md
  docs/adr/0010-accounts-and-payments-model.md docs/design docs/user-guide
  docs/developer/README.md docs/developer/workflow.md docs/developer/agent-handover.md
  docs/developer/backend-admin-stores.md docs/developer/backend-checkout.md docs/developer/backend-media.md
  docs/developer/backend-orders-api.md docs/developer/backend-products-api.md docs/developer/backend-refunds.md
  "docs/developer/backend-store-*.md" "docs/developer/backend-storefront-*.md"
  docs/developer/backend-stripe-connect.md docs/developer/dashboard-products.md
  docs/developer/dashboard-store-scope.md "docs/developer/storefront-*.md"
  docs/developer/legacy-browser-regressions.md docs/developer/known-issues.md docs/developer/template-export.md
  # frontend
  "nextjs-frontend/scripts/foundation-done-check*"
  "nextjs-frontend/src/app/(admin)/admin/stores"
  nextjs-frontend/src/app/actions/admin-store-actions.ts nextjs-frontend/src/app/actions/connect-actions.ts
  nextjs-frontend/src/app/actions/onboarding-actions.ts nextjs-frontend/src/app/actions/order-actions.ts
  nextjs-frontend/src/app/actions/product-actions.ts nextjs-frontend/src/app/actions/product-import-actions.ts
  nextjs-frontend/src/app/actions/store-actions.ts nextjs-frontend/src/app/actions/store-settings-actions.ts
  nextjs-frontend/src/app/dashboard/onboarding nextjs-frontend/src/app/dashboard/orders
  nextjs-frontend/src/app/dashboard/products nextjs-frontend/src/app/dashboard/settings/store
  nextjs-frontend/src/app/storefront nextjs-frontend/src/app/storefront-preview
  nextjs-frontend/src/components/dashboard/store-switcher.tsx nextjs-frontend/src/components/dashboard/new-store-dialog.tsx
  nextjs-frontend/src/components/dashboard/hide-on-onboarding.tsx nextjs-frontend/src/components/dashboard/store-setup-state.tsx
  nextjs-frontend/src/components/dashboard/orders nextjs-frontend/src/components/dashboard/products
  nextjs-frontend/src/components/dashboard/settings/connect-payments-panel.tsx
  nextjs-frontend/src/components/dashboard/settings/store-settings-form.tsx
  nextjs-frontend/src/components/dashboard/settings/form-page.tsx
  nextjs-frontend/src/components/dashboard/overview/needs-attention.tsx
  nextjs-frontend/src/components/dashboard/overview/recent-orders-panel.tsx
  nextjs-frontend/src/components/dashboard/overview/overview-kpi-strip.tsx
  nextjs-frontend/src/components/dashboard/overview/defaults.ts nextjs-frontend/src/components/dashboard/overview/fixtures.ts
  nextjs-frontend/src/components/onboarding nextjs-frontend/src/components/storefront
  nextjs-frontend/src/lib/api/admin-stores.ts nextjs-frontend/src/lib/api/cart.ts nextjs-frontend/src/lib/api/checkout.ts
  nextjs-frontend/src/lib/api/connect.ts nextjs-frontend/src/lib/api/onboarding.ts nextjs-frontend/src/lib/api/orders.ts
  nextjs-frontend/src/lib/api/products.ts nextjs-frontend/src/lib/api/storefront.ts
  nextjs-frontend/src/lib/api/storefront-catalogue.ts nextjs-frontend/src/lib/api/store-settings.ts
  nextjs-frontend/src/lib/api/stores.ts
  nextjs-frontend/src/lib/onboarding nextjs-frontend/src/lib/orders nextjs-frontend/src/lib/products
  nextjs-frontend/src/lib/store-settings nextjs-frontend/src/lib/storefront nextjs-frontend/src/lib/stores
  # frontend unit tests of the files above
  nextjs-frontend/src/__tests__/unit/db nextjs-frontend/src/__tests__/unit/products nextjs-frontend/src/__tests__/unit/storefront
  nextjs-frontend/src/__tests__/unit/scripts/foundation-done-check.test.ts
  "nextjs-frontend/src/__tests__/unit/actions/{admin-store,connect,create-additional-store,onboarding,order,product,product-image,product-import,store,store-settings}-action*.test.ts"
  "nextjs-frontend/src/__tests__/unit/api/{admin-stores,cart,checkout,connect,create-store-in-organization,onboarding,orders,products-image,products-import,products,retry-provisioning,store-settings,storefront-catalogue,storefront,stores}.test.ts"
  "nextjs-frontend/src/__tests__/unit/app/{admin-store-pages,admin-store-row-actions,products-pages,store-setup-guard-pages}.test.tsx"
  "nextjs-frontend/src/__tests__/unit/app/storefront-*.test.ts" "nextjs-frontend/src/__tests__/unit/app/storefront-*.test.tsx"
  "nextjs-frontend/src/__tests__/unit/components/{connect-payments-panel,hide-on-onboarding,new-store-dialog,onboarding-form,provisioning-status,provisioning-status-stalled,status-pill,store-switcher,storefront}.test.tsx"
  "nextjs-frontend/src/__tests__/unit/components/dashboard/{fulfil-form,image-upload-form,product-import-dialog,products,store-settings-form,store-setup-state}.test.tsx"
  "nextjs-frontend/src/__tests__/unit/lib/{onboarding-schema,store-provisioning,store-selection,store-settings-form}.test.ts"
  "nextjs-frontend/src/__tests__/unit/middleware/proxy-{path-preview,subdomain}.test.ts"
  # frontend e2e
  "nextjs-frontend/src/__tests__/e2e/{admin-stores,connect-onboarding,merchant-onboarding,new-store,orders-management,product-import,product-management,store-settings,store-switcher}.spec.ts"
  "nextjs-frontend/src/__tests__/e2e/storefront-*.spec.ts"
  "nextjs-frontend/src/__tests__/e2e/helpers/*.py"
  nextjs-frontend/src/__tests__/e2e/helpers/orders-e2e.ts nextjs-frontend/src/__tests__/e2e/helpers/products-e2e.ts
  # backend
  fastapi_backend/CLAUDE.md fastapi_backend/.env.example
  "fastapi_backend/alembic_migrations/versions/*.py" fastapi_backend/alembic_store.ini fastapi_backend/alembic_store
  fastapi_backend/commands/migrate_stores.py fastapi_backend/commands/sweep_checkout_orders.py
  fastapi_backend/app/api/merchant.py fastapi_backend/app/api/store_db.py
  "fastapi_backend/app/api/v1/{admin_stores,cart,categories,checkout,internal_cart_purge,internal_provisioning,media,order_refunds,orders,org_connect,product_import,products,store_retry,store_settings,storefront,storefront_catalogue,stores,webhooks_connect}.py"
  "fastapi_backend/app/core/{qstash_signature,store_crypto,stripe_checkout,stripe_connect,stripe_refunds}.py"
  fastapi_backend/app/models/platform/store.py fastapi_backend/app/models/platform/stripe_connect_event.py
  "fastapi_backend/app/repositories/{admin_stores,checkout,connect_events,merchant,org_connect,store_cart,store_catalogue,store_orders,store_settings,storefront}.py"
  "fastapi_backend/app/services/{admin_stores,media_uploads,product_import,provisioning_readiness,storefront,storefront_catalogue,stripe_connect}.py"
  "fastapi_backend/app/services/merchant*.py" "fastapi_backend/app/services/store_*.py"
  # backend tests of the files above
  "fastapi_backend/tests/{fakes_admin_stores,fakes_connect,fakes_provisioning,isolation_world,qstash_tokens}.py"
  fastapi_backend/tests/api/products_support.py
  "fastapi_backend/tests/api/test_{admin_store,admin_stores,cart,checkout,internal,media,merchant,order,orders,product,products,store,storefront,tenant,org_connect,stripe_connect}*.py"
  "fastapi_backend/tests/core/test_{qstash_signature,r2_config,store_crypto,stripe_checkout,stripe_checkout_expiry,stripe_connect,stripe_refunds,startup_provisioning_warning}.py"
  "fastapi_backend/tests/repositories/test_{admin_stores,store_secrets_e2e}.py"
  "fastapi_backend/tests/services/test_{admin_store,admin_stores,catalogue,media,merchant,product,provisioning,store,storefront,stripe_connect}*.py"
  "fastapi_backend/tests/commands/test_{migrate_stores,sweep_checkout_orders}.py"
)

if [ ${#PATHS[@]} -eq 0 ]; then
  removed=0
  for pattern in "${STORECART_ONLY[@]}"; do
    # Brace and glob expansion happen inside the target; an unmatched pattern is a mistake worth seeing.
    matches=()
    while IFS= read -r m; do matches+=("$m"); done < <(cd "$TARGET" && eval "printf '%s\n' $pattern" | while read -r p; do [ -e "$p" ] && echo "$p"; done)
    if [ ${#matches[@]} -eq 0 ]; then echo "  (no match) $pattern" >&2; continue; fi
    for m in "${matches[@]}"; do rm -rf -- "$TARGET/$m"; removed=$((removed + 1)); done
  done
  echo "removed $removed StoreCart-only paths"
fi

# ---------------------------------------------------------------- brand and Jira scrub
# Lockfiles, the OpenAPI schema and the generated client are regenerated in the template, never edited.
scrub_targets() {
  grep -rlI -E 'StoreCart|storecart|KAN-[0-9]+|vpachipulusu' "$TARGET" \
    --exclude=package-lock.json --exclude=uv.lock --exclude=openapi.json --exclude=requirements.txt \
    --exclude-dir=generated --exclude-dir=.git || true
}
count=0
while IFS= read -r file; do
  [ -n "$file" ] || continue
  sed -i -E \
    -e 's/StoreCart API/Your App API/g' \
    -e 's/StoreCart/Your App/g' \
    -e 's/storecart\.atlassian\.net\/browse\/KAN-[0-9]+//g' \
    -e 's/storecart/your-app/g' \
    -e 's#vpachipulusu/store-cart-next\.js#your-org/your-app#g' \
    -e 's/ ?\(KAN-[0-9]+(, ?KAN-[0-9]+)*\)//g' \
    -e 's/KAN-[0-9]+(, ?KAN-[0-9]+)*:? ?//g' \
    -e 's/\(, /(/g' \
    "$file"
  count=$((count + 1))
done < <(scrub_targets)
echo "scrubbed $count files"

left="$(scrub_targets | wc -l | tr -d ' ')"
if [ "$left" != "0" ]; then
  echo "still mentions StoreCart or a Jira key (fix by hand):" >&2
  scrub_targets >&2
fi
echo "done: $TARGET"
