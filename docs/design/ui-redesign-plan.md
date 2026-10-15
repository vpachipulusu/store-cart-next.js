# StoreCart UI Redesign Plan

Status: proposal for owner review. Author: UI/product design pass (design work only; no application code was changed).

**There is no Figma file yet.** No Figma tool was available in this environment, so nothing was created in Figma. This document is a Figma-ready spec (named tokens, component specs, frame descriptions with sizes, grids, spacing and states) that someone can build in Figma directly. The companion file `docs/design/ui-concepts.html` is an HTML concept board of the same designs. All names, prices, plan limits and figures in the mockups are **example data**.

Contents: 1 Direction, 2 Findings, 3 Surfaces and states, 4 Tokens, 5 Components, 6 Frame specs, 7 Content-state tables, 8 Phasing and stories, 9 Accessibility and responsive checklist, 10 Verification record, 11 Open questions.

---

## 1. Design direction: "Ledger and Brass"

StoreCart sells trust to small merchants who are doing everything themselves. The interface should feel like a well-kept shop ledger: ivory paper, navy ink, one brass accent, ruled lines instead of boxes, and figures that line up.

What stays (it is already the strongest part of the app, `globals.css:7-60`): warm ivory background, deep navy foreground, champagne gold accent, navy-charcoal dark mode, `--radius: 0.625rem`.

What changes and why:

| Today | Direction | Reason |
|---|---|---|
| Gold used as a background for white text | Gold is a surface only with navy text; a darker "brass ink" is used when gold must be text | White on gold is 2.11:1 (fails AA). Navy on gold is 8.49:1 |
| Headings accidentally Georgia | Deliberate display serif (Fraunces proposed) for h1-h3 and big figures; body stays admin-selectable | `--font-display` is never defined (finding F2). A serif display against a neutral sans body gives the "ledger" voice and a real pairing |
| Identical rounded cards with hover glow everywhere | Hairline-ruled panels, one elevation, no gold glows. Hierarchy from scale contrast, not from boxes | 23 `theme-card` uses make every region equal weight |
| Boilerplate landing, account-centric dashboard | Merchant workspace: sidebar, KPI strip, orders table, plan usage | Product is a multi-tenant store platform (Free/Pro/Enterprise with store, product and staff limits) |
| Colour-only status (Badge default = navy, destructive = red) | Status pills with icon, text and tint; semantic good/warning/critical/info tokens | Colour must not carry meaning alone |

Anti-template checks (from the web design-quality rules): at least four of the required qualities are met per surface: scale contrast (Fraunces vs body), intentional rhythm (48/64/96 section spacing against 12/16 inside tables), layering (inverse sidebar and inverse featured plan), semantic colour, and designed hover/focus states. No purple, gradient blobs, cards inside cards, or emoji.

---

## 2. Findings (evidence)

Paths are relative to `nextjs-frontend/`. Line numbers were read from the working tree on 2026-10-14.

| # | Finding | Evidence | Severity |
|---|---|---|---|
| F1 | White text on gold fails WCAG AA (2.11:1). 14 occurrences of `bg-theme-accent text-white` in 11 files, including the primary CTA on landing, login, signup, pricing, billing | `src/app/page.tsx:29,156`; `src/app/pricing/page.tsx:198`; `src/app/dashboard/page.tsx:138`; `src/app/contact/page.tsx:107`; `src/app/dashboard/settings/page.tsx:304`; `src/app/dashboard/profile/page.tsx:315`; `src/app/dashboard/settings/billing/page.tsx:307`; `src/components/auth/login-form.tsx:133`; `src/components/auth/signup-form.tsx:183`; `src/components/pricing/pricing-card.tsx:129,174`; `src/components/pricing/billing-toggle.tsx:23,34` | High |
| F2 | `font-display` maps to `var(--font-display)` which nothing defines; headings fall back to Georgia by accident. `h1-h3` use it | `tailwind.config.ts:21`; `src/app/globals.css:133-138`; no definition in `src/config/fonts.ts` or `src/app/layout.tsx` (grep for `--font-display` finds only the Tailwind line) | Medium |
| F3 | The runtime tokens are not the ones in `globals.css`: the root layout injects `:root{...} .dark{...}` generated from an admin-selected preset, overriding `globals.css`. A token fix made only in `globals.css` will not reach production. Two presets exist: `luxury` (gold) and `plain` (blue `217 91% 60%`; white on it is 3.64:1, also failing) | `src/app/layout.tsx:111,118`; `src/config/themes.ts:10-43,133-216,219-231` | High (changes how Phase 0 is built) |
| F4 | Body font is admin-selectable (10 loaders, all with `variable: '--font-body'`; only the active one is applied to `<body>`), so the display font must be a separate, always-loaded token | `src/config/fonts.ts:25-86,92-163`; `src/app/layout.tsx:110-113,121` | Info |
| F5 | Buttons are 36px high by default (`h-9`), 32px small, 40px large; below the 44px target. Focus ring on buttons is `ring-1`; the global focus ring is gold at 50% opacity, which is under 3:1 on ivory (gold vs ivory 2.02:1 before the opacity) | `src/components/ui/button.tsx:8,24-27`; `src/app/globals.css:129-131` | High |
| F6 | Control borders use the hairline `--input` (`35 20% 89%`), 1.21:1 against the page; WCAG 1.4.11 needs 3:1 for the edge of a control | `src/app/globals.css:42`; `src/components/ui/input.tsx:11` | Medium |
| F7 | Muted text on dark card is 5.15:1 and on light is 4.70:1; passes but with almost no margin (translucent overlays and the `ring/50` fall below) | `src/app/globals.css:30,85` | Low |
| F8 | Landing page is the boilerplate template: "Next.js 16 + React 19 + TypeScript", "Build modern web apps faster than ever", a link to `github.com/yourusername/your-repo`, four identical icon cards, a tech-stack list. It says nothing about StoreCart | `src/app/page.tsx:14,16-23,37-43,62-104,111-138,146-149` | High |
| F9 | Dashboard is account-centric, not merchant-centric: top bar with five links, four stat cards, four identical quick-action cards, then account info, login history and notifications | `src/app/dashboard/layout.tsx:91-131`; `src/app/dashboard/page.tsx:149-276,280-389` | High |
| F10 | The dashboard primary nav is `hidden ... md:flex`; the header component only contains a user dropdown, so phones have no navigation to the other dashboard pages | `src/app/dashboard/layout.tsx:98`; `src/components/dashboard/dashboard-header.tsx` (DropdownMenu only, no mobile menu found) | High |
| F11 | Cards inside cards and uniform emphasis: notification rows are bordered cards inside a card; status uses the default navy Badge | `src/app/dashboard/page.tsx:393-429`; `src/components/ui/badge.tsx:11-18` | Medium |
| F12 | Pricing: featured plan is `scale-105` with a gradient strip, white-on-gold badge and button; yearly shows monthly equivalent; error path uses `alert()`; plan features in the config are placeholders ("Example: Up to 3 projects"), so no limits are shown | `src/components/pricing/pricing-card.tsx:120-130,174,67`; `src/config/subscriptions.ts:41-70` | High |
| F13 | Login error box has no `role="alert"`, and does not repeat the field context; form has `noValidate` so errors depend on zod messages being associated with fields (shadcn `FormMessage`, not verified here) | `src/components/auth/login-form.tsx:80-83` | Medium |
| F14 | No 2FA code step in the sign-in form today; 2FA management lives on the security page only | `src/components/auth/login-form.tsx` (no code state); `src/app/dashboard/security/page.tsx:10-13` (get2FAStatusAction etc.) | Info (the 2FA frame is a proposed flow; see open questions) |
| F15 | Motion: every `stagger-children` item starts at `opacity: 0`; there is no `prefers-reduced-motion` handling in `globals.css`; the shimmer runs 8s infinite | `src/app/globals.css:179-205` | Medium |

---

## 3. Surfaces, jobs, actions, viewports

Target viewports for every screen: **375x812** (phone), **768x1024** (tablet), **1440x900** (desktop). Both light and dark are designed for all of them.

| Surface | User | Job to be done | Primary action | Hierarchy (top to bottom) |
|---|---|---|---|---|
| Landing | Prospective merchant | Decide if StoreCart fits a small shop | Start free | Headline, ledger visual, three steps, one product proof with plan usage, CTA band |
| Merchant dashboard | Store owner or staff | See what needs attention and how the shop is doing | Add product | Page title and action, attention list, KPI strip, recent orders, plan usage |
| Pricing | Merchant comparing plans | Pick the plan whose limits fit | Choose Pro (featured) | Title, billing switch, three plans with limits first, fine print |
| Sign-in | Returning user | Get in with least friction | Sign in, then Verify | Title, error (if any), fields, primary button, recovery links |
| Admin users list | Platform admin | Find a user and act on their account | Search; row actions | Title, search and filters, table, pagination |

---

## 4. Design tokens

All colour tokens are HSL triples (no `hsl()` wrapper) so they drop into `globals.css` and the `ThemeModeVariables` in `src/config/themes.ts`. Hex values are the computed sRGB. Names marked **new** do not exist today. In Figma: create one variable collection "Color" with modes `Light` and `Dark`, using the same names.

### 4.1 Colour: surface, text, brand

| Token | Light HSL (hex) | Dark HSL (hex) | Notes |
|---|---|---|---|
| `--background` | `40 33% 98%` (#fcfaf8) | `224 50% 6%` (#080c17) | unchanged |
| `--card` (raised surface) | `40 33% 99%` (#fdfdfc) | `224 45% 9%` (#0d1221) | unchanged |
| `--secondary` / sunken | `35 25% 93%` (#f2eee9) | `224 35% 15%` (#192034) | unchanged; used for table header, hover |
| `--foreground` | `222 47% 11%` (#0f1729) | `38 25% 90%` (#ece7df) | unchanged |
| `--muted-foreground` | **`220 12% 38%`** (#555d6d), was `220 10% 46%` | **`220 15% 66%`** (#9ba4b5), was `220 15% 55%` | raised for margin |
| `--border` (hairline, decorative only) | `35 20% 89%` (#e9e4dd) | `224 35% 15%` | unchanged; never the only edge of a control |
| `--input` (control edge) | **`35 12% 54%`** (#988c7c), was `35 20% 89%` | **`224 20% 46%`** (#5e6a8d), was `224 35% 15%` | 3:1 non-text rule |
| `--ring` (focus) | **`222 47% 11%`** (navy) | `38 65% 55%` (gold, unchanged) | gold ring on ivory is only 2.02:1; use navy in light |
| `--accent` / **`--cta`** (brass surface) | `38 65% 60%` (#dbab57) | `38 65% 55%` (#d7a042) | **new alias `--cta`**, see below |
| `--accent-foreground` / **`--cta-foreground`** | `222 47% 11%` (#0f1729) | `224 50% 6%` (#080c17) | navy on brass |
| **`--cta-hover`** | `38 65% 54%` (#d69e3d) | `38 65% 62%` (#ddaf5f) | new |
| **`--accent-ink`** (brass as text) | `38 80% 27%` (#7c540e) | `38 70% 66%` (#e5b86c) | new; eyebrows, links, big numerals on paper |
| **`--feature`** (inverse panel: sidebar, featured plan, CTA band) | `222 47% 11%` | `230 50% 21%` (#172250 for the featured plan; sidebar uses `224 45% 8%`) | new |

**Why `--cta` is a separate token (finding F3).** The admin theme system swaps `--theme-accent` and `--accent` per preset. In the `plain` preset `--accent` is a pale grey (`210 40% 96%`) and `--theme-accent` is blue, and white on that blue is 3.64:1. Components must therefore never pick "white" or "navy" themselves. Each preset supplies a matched pair:

| Preset | Light `--cta` / `--cta-foreground` | Dark `--cta` / `--cta-foreground` | Contrast |
|---|---|---|---|
| luxury | `38 65% 60%` / `222 47% 11%` | `38 65% 55%` / `224 50% 6%` | 8.49 / 8.37 |
| plain | `221 83% 53%` / `0 0% 100%` | `217 91% 60%` / `222 84% 5%` | 5.17 / 5.50 |

### 4.2 Colour: semantic status (new)

Each status has a tint `-bg` and a text colour `-fg`. Use them as a pair, always together with an icon and a text label.

| Token pair | Light fg on bg | Dark fg on bg | Meaning in StoreCart |
|---|---|---|---|
| `--good-fg` / `--good-bg` | `152 60% 22%` on `152 40% 91%` | `152 50% 64%` on `152 40% 13%` | Paid, Fulfilled, Active, Verified |
| `--warn-fg` / `--warn-bg` | `30 90% 24%` on `42 90% 89%` | `40 85% 66%` on `38 60% 13%` | Pending, Low stock, Near limit |
| `--crit-fg` / `--crit-bg` | `0 70% 36%` on `0 80% 96%` | `0 85% 74%` on `0 55% 15%` | Failed, Limit reached, Domain error |
| `--info-fg` / `--info-bg` | `217 70% 34%` on `217 80% 95%` | `217 90% 76%` on `217 50% 15%` | To fulfil, Trial, Informational |
| `--destructive` (filled danger button, white text) | **`0 72% 42%`**, was `0 72% 51%` | **`0 70% 42%`**, was `0 62% 30%` | delete, disable |

Tailwind mapping (additive): `good: { DEFAULT: 'hsl(var(--good-bg))', foreground: 'hsl(var(--good-fg))' }`, same for `warn`, `crit`, `info`, `cta`, plus `accent-ink` and `feature`. Charts: keep `--chart-1..5`, but pair with direct labels; do not use `--chart-4` purple for anything new (`280 30% 55%` in light).

### 4.3 Contrast table (WCAG 2.2 relative-luminance formula; computed with a Node script)

AA targets: normal text 4.5:1, large text and non-text UI 3:1.

| Theme | Pair | Ratio | Result |
|---|---|---|---|
| Light | navy text on ivory background | 17.17 | pass |
| Light | muted text (new) on ivory / on secondary | 6.36 / 5.73 | pass (old 46% value: 4.70) |
| Light | **white on gold (current bug)** | **2.11** | **fail** |
| Light | navy on gold (new CTA) / on gold hover | 8.49 / 7.50 | pass |
| Light | brass ink on ivory (links, eyebrow) | 6.44 | pass |
| Light | brass ink on secondary | 5.81 | pass |
| Light | gold vs ivory as focus ring | 2.02 | fail, so ring becomes navy: 17.17 on ivory, 17.56 on card |
| Light | good / warning / critical / info text on own tint | 7.00 / 7.50 / 7.13 / 7.57 | pass |
| Light | white on destructive, old `0 72% 51%` / new `0 72% 42%` | 4.80 / 6.48 | pass both; new gives margin |
| Light | control edge `--input` (new) vs ivory / vs card | 3.16 / 3.24 | pass (non-text 3:1) |
| Light | old hairline as control edge | 1.21 | fail |
| Light | ivory text on navy panel; gold on navy panel | 17.17; 8.49 | pass |
| Light | muted ivory-grey on navy panel (`38 20% 76%`) | 10.46 | pass |
| Light | `plain` preset: white on blue accent (current) | 3.64 | fail |
| Light | `plain` CTA new pair white on `221 83% 53%` | 5.17 | pass |
| Dark | ivory text on night background | 15.87 | pass |
| Dark | muted text (new) on background / on card | 7.79 / 7.44 | pass (old on card: 5.15) |
| Dark | navy on gold (CTA) / on gold hover | 8.37 / 9.65 | pass |
| Dark | white on gold | 2.33 | fail, not used |
| Dark | brass ink on night | 10.61 | pass |
| Dark | gold vs night as focus ring | 8.37 | pass |
| Dark | good / warning / critical / info text on own tint | 7.92 / 8.76 / 6.68 / 7.66 | pass |
| Dark | critical text on card | 7.57 | pass |
| Dark | white on destructive, old `0 62% 30%` / new `0 70% 42%` | 10.24 / 6.53 | pass both |
| Dark | control edge `--input` (new) vs night / vs card | 3.65 / 3.48 | pass |
| Dark | muted text on featured plan panel (`230 50% 21%`), ivory, gold | 5.92, 12.06, 6.36 | pass |
| Dark | `plain` preset: white on `217 91% 60%` / new navy on it | 3.64 / 5.50 | white fails, new pair passes |

Rule for engineers: the contrast of any new foreground/background pair must be added to a unit test (see story P0.1) so a theme preset cannot regress it.

### 4.4 Typography

Two families (matches the "max two families" performance rule): display `--font-display` (always loaded) and body `--font-body` (admin-selectable via `src/config/fonts.ts`, unchanged).

Proposed display font: **Fraunces** (variable, `next/font/google`, `axes: ['opsz']`, weights 400 and 600, `display: 'swap'`, `variable: '--font-display'`). Fallback stack `Georgia, 'Times New Roman', serif`, which is what headings render with today, so a font-load failure degrades to the current look. Alternatives if the owner dislikes Fraunces: Newsreader, Source Serif 4, or Instrument Serif (display-only).

| Role | Family / weight | Size (mobile to desktop) | Line height | Use |
|---|---|---|---|---|
| Display | display 600 (italic 400 for one emphasised word) | `clamp(2.25rem, 1.2rem + 4vw, 3.75rem)` | 1.05 | Landing and pricing h1 only |
| Heading 1 | display 600 | `clamp(1.75rem, 1.3rem + 1.6vw, 2.375rem)` | 1.1 | page titles |
| Heading 2 | display 600 | `clamp(1.5rem, 1.2rem + 1.5vw, 2.5rem)` | 1.15 | section titles |
| Panel title | body 600 | 1rem | 1.4 | panel headers, h3 below the fold |
| Body | body 400 | 1rem | 1.55 | default |
| Body small | body 400 | 0.875rem | 1.5 | hints, captions (never below 0.8125rem) |
| Label / eyebrow | body 600, caps, +0.08em | 0.8125rem | 1.3 | eyebrows, table headers (0.75rem for table head only) |
| Figure | display 600, `tabular-nums` | 1.5rem to 2rem | 1.15 | KPI values, prices (3rem on plan cards) |

Numerals in tables and prices use `font-variant-numeric: tabular-nums`. Rely on `text-wrap: balance` for headings (already a utility, `globals.css:260`).

### 4.5 Spacing, radius, elevation, motion

| Group | Tokens |
|---|---|
| Spacing (4pt) | 4, 8, 12, 16, 24, 32, 48, 64, 96. Inside controls and tables 8-16; between panels 24; between sections 64-96 (rhythm is deliberately uneven) |
| Radius | controls (buttons, inputs) 10px (= existing `--radius`); panels 14px; pills full. Do not use one radius for everything |
| Elevation | `e0` hairline border only (default); `e1` `0 1px 2px navy/8%` (sticky bars); `e2` `0 10px 30px navy/14%` (popover, featured plan, browser mockups). Remove gold glow hovers (`.theme-card:hover`, `.theme-border:hover`, `globals.css:159-177`) |
| Motion | `--t-fast` 120ms, `--t-base` 200ms, ease `cubic-bezier(.16,1,.3,1)` (the existing curve). Animate only transform and opacity. Reveal-up only on first paint of a page, 10px travel (was 20px). `prefers-reduced-motion: reduce` sets all durations to ~0 and removes reveal and shimmer |
| Touch target | 44px minimum height for every button, input, tab, nav link, pill that is interactive; 24px is the WCAG 2.2 AA floor and is only acceptable for inline text links within a sentence |
| Focus | 3px outline, 2px offset, colour `--ring` (navy in light, gold in dark; gold on every inverse panel), never `outline: none` without a replacement |

---

## 5. Component specs

Build each as a Figma component set with the listed variants and states (default, hover, focus-visible, active, disabled, loading, error where relevant), in Light and Dark modes.

### 5.1 Button

| Variant | Fill / text | Border | Use |
|---|---|---|---|
| `accent` (new, replaces every `bg-theme-accent text-white`) | `--cta` / `--cta-foreground`; hover `--cta-hover`; no coloured glow shadow | none | One per view: the primary action |
| `default` | `--primary` / `--primary-foreground` | none | Secondary-strong, e.g. Save in settings |
| `outline` | transparent / `--foreground`; hover `--secondary` | 1px `--input` | Secondary |
| `ghost` | transparent; hover `--secondary` | none | Tertiary, toolbar |
| `destructive` | `--destructive` / white | none | Delete, disable, only after a confirm |
| `link` | `--accent-ink` text, underline offset 3px | none | Inline |

Sizes: `lg` 48px, `default` 44px (was 36), `sm` 40px used only in dense desktop tables and never the only target for a destructive action, `icon` 44x44. Padding 24px horizontal at `default`. Font 15px/600. Loading state: spinner replaces the leading icon, label changes ("Signing in..."), `aria-busy="true"`, button stays the same width. Disabled: 55% opacity, `aria-disabled` for links. Focus: 3px outline as above. Active: 1px translateY.

### 5.2 Navigation shell with sidebar (dashboard and admin)

- Desktop (container width 900px and up): 240px fixed sidebar on `--feature` (dark navy in both themes), content column on `--background`. Sidebar order: store switcher (52px, shows store name, plan, chevron; `aria-haspopup="menu"`), main nav, footer with user and role.
- Main nav items (44px, 18px icon + label): Overview, Orders (count badge), Products, Customers, Domains, Plan and billing, Settings (profile, security, notifications and login history live here, answering finding F9). Active item: lighter fill plus a 3px gold bar on the inline-start edge and `aria-current="page"`.
- Below 900px: sidebar hidden; bottom tab bar with four items (Overview, Orders, Products, More), 56px high, gold 3px top bar for current, `More` opens a sheet with the rest. This fixes finding F10.
- Landmarks: `<aside aria-label="Workspace">`, `<nav aria-label="Main">`, `<main>`; skip link first in tab order.
- Admin uses the same shell with the nav `Users, Subscriptions, Analytics, Audit logs, SEO, Settings` and a visible "Admin" label in the switcher slot so context is unmistakable.

### 5.3 KPI strip

One panel divided by hairlines, not four cards. 4 columns at container 760px and up, 2x2 below. Each cell: label (13px, muted), value (display 600, 24-32px, tabular), delta (icon + text, 13px/600, colour good/crit/muted) with screen-reader text "up 12% on the previous 7 days", 28px sparkline (decorative, `aria-hidden`). States: loading (label visible, value and sparkline skeleton at 32x120), empty ("No orders yet" in muted text with a link to add a product), error (cell shows "Could not load" with a retry text button, other cells unaffected).

### 5.4 Table

Panel with a 14px radius, header row on `--secondary`, 12px/16px cell padding, hairline row dividers, row hover `--secondary`, header labels 12px caps. Numeric columns right-aligned, tabular figures. Links in the first column. Below 640px container width the header is visually hidden and each row becomes a two-column stacked item (identifier and customer on the first line, status pill and total on the second). Always a `<caption>` (visually hidden) and `<th scope="col">`. Sortable headers are buttons with `aria-sort`. Pagination: previous/next buttons 44px plus "Showing 1 to 25 of 312". Row actions: a 44px icon button opening a menu; every action also reachable from the row's detail page.

### 5.5 Status pill

Height 24px, padding 2px 10px 2px 8px, 14px icon + 13px/600 label, full radius. Always icon + text + tint (never colour only).

| Status | Pair | Icon |
|---|---|---|
| Paid, Fulfilled, Active, Verified | good | check |
| Pending, Low stock, Near limit | warn | clock |
| Failed, Limit reached, Error | crit | triangle alert |
| To fulfil, Trial, New | info | box |
| Refunded, Draft, Archived | neutral (`--secondary`, `--foreground`) | undo / pencil |

Replace `Badge` usages for status (`dashboard/page.tsx:158-160,373-378`); keep `Badge` for counts and labels.

### 5.6 Plan card

Three plans in a row at container width 820px and up, stacked below. Same height via `align-items: stretch`; CTA pinned to the bottom. Contents in order: name (display 600, 24px), one-line tagline, price (display 600, 48px tabular) with "/ month" and a billed line (reserve 24px of height so the columns do not jump when toggling), limits list (stores, products, staff seats first, each with the number in bold), CTA. The featured plan is an inverse panel on `--feature` with a 2px gold border, a "Most chosen" pill and a gold CTA; no scale transform and no gradient strip. States: current plan (CTA becomes "Current plan", disabled, with a good pill "Active"), loading price (price area skeleton), price unavailable (shows "Contact us" with CTA to contact, not 0), checkout error (inline `role="alert"` below the CTA, replacing the `alert()` call at `pricing-card.tsx:67`).

### 5.7 Billing toggle

A `role="radiogroup"` with two `role="radio"` buttons (44px, min width 96px). Selected: `--foreground` fill with `--background` text (replaces white-on-gold at `billing-toggle.tsx:23,34`). The yearly label carries "save 17%" as text (example figure). Arrow keys move selection; selection is announced.

### 5.8 Form field with error

Stack: label (15px/500), control (44px, 1px `--input` edge, 10px radius), optional hint (14px muted), error. Error state: 2px `--crit-fg` border, `aria-invalid="true"`, error line with icon + text in `--crit-fg` linked via `aria-describedby`; do not rely on colour. Form-level errors use an alert panel (`role="alert"`, crit tint, icon, bold summary line and a plain-language sentence) above the fields; on submit focus moves to the first invalid field if field errors exist, else to the alert. Placeholder is never the label. Required fields are marked in the label text, not just with an asterisk. Code field (2FA): single input, `inputmode="numeric"`, `autocomplete="one-time-code"`, 56px high, 28px type with 0.7em letter spacing (single input is better for paste, password managers and screen readers than six boxes).

---

## 6. Frame specs (Figma-ready)

File structure: pages `00 Cover`, `01 Tokens`, `02 Components`, `03 Landing`, `04 Dashboard`, `05 Pricing`, `06 Sign-in`, `07 Admin users`. Frame naming `<Screen>/<Viewport>/<Theme>/<State>`, for example `Dashboard/Desktop/Light/Default`.

Layout grids: Desktop 1440x900: 12 columns, margin 80, gutter 24, content max width 1180 (centred). Tablet 768x1024: 8 columns, margin 32, gutter 24. Phone 375x812: 4 columns, margin 16, gutter 16. Dashboard desktop: 240px sidebar plus fluid content with 32px side padding. Vertical rhythm: 8pt baseline, sections 64-96.

### 6.1 Landing

- Nav, 72px: logo (26px mark + wordmark, Fraunces 20px), links Features, Pricing, For agencies; right side Sign in (ghost) and Start free (accent). On phones, links wrap under the logo as a second row; Sign in hidden, Start free kept.
- Hero (desktop): two columns 1.1fr / 0.9fr, 96px top padding. Left: eyebrow "Online stores for independent merchants", h1 Display "Open your store this *afternoon.*" (italic brass-ink on the last word only), 18px muted subcopy (max width 46ch), CTA row (Start free accent, See plans and limits outline), fine print "No card needed for the Free plan." Right: ledger illustration (panel with today's takings in display figures, a delta pill, three order rows with status pills), caption "Illustration with example data". Tablet: stacked, illustration below. Phone: stacked, illustration full width.
- Three numbered steps (01, 02, 03 in Fraunces brass-ink): Add your products, Connect Stripe, Point your domain; hairlines between columns on desktop, between rows on phone.
- Product proof: two columns. Left: eyebrow, h2 "One calm place for orders, stock and customers.", three short definitions (Staff roles, Limits you can see, Your domain your brand). Right: plan usage panel with three meters.
- CTA band: inverse panel, h2 "Your first order is closer than your first invoice.", one sentence, accent button.
- Footer: copyright, Pricing, Terms, Privacy. No GitHub link, no tech stack list.

### 6.2 Merchant dashboard

- Desktop: shell from 5.2. Page header: h1 "Good morning, Priya" with sentence-case subline and the date range, right-aligned Add product (accent).
- KPI strip (5.3): Revenue, Orders, Conversion, Average order, over a selectable range (7 days default; a 44px select).
- Two columns at container width 1000px and up (1.8fr / 1fr): left Recent orders table (5 rows, link "View all orders"); right Needs attention list (counts in pills, each with a verb link) above Plan usage (meters for Products, Staff seats, Stores; a Limit reached pill when full; Compare plans outline button).
- Tablet: sidebar collapses to the tab bar; single column. Phone: KPI 2x2, table becomes stacked rows, plan usage last.
- Moved out of Overview: account information, login history, notification feed (now Settings, Notifications bell in the header remains). Subscription success handler stays.

### 6.3 Pricing

- Header: eyebrow Plans, h1 "Pay for the size of your shop.", one-sentence subcopy, billing radiogroup.
- Plans: 3 columns (5.6). Order Free, Pro (featured), Enterprise. Limits lead each list. Fine print below: "Example prices and limits for design review only" (remove for production).
- Comparison table for tablet and up (below the plans): rows Stores, Products, Staff seats, Custom domain, Support; columns by plan; a real `<table>`. Phone: accordion per plan.
- FAQ (4 items, native `<details>`): changing plans, what happens at a limit, refunds, taxes.

### 6.4 Sign-in (two states plus mobile)

- Layout: two columns at container width 760px and up: left inverse brand panel (logo, h2 "Back to your shop.", one sentence), right form column (max 400px). Phone: form only, small logo at top.
- State A (default) fields: Email, Password with "Forgot password?" aligned right of the label (44px target), Sign in (accent, full width), then "New to StoreCart? Create a free store".
- State B (error, shown on the concept board): alert panel (`role="alert"`) "We could not sign you in. That email and password do not match. Check them and try again, or reset your password." Email field in error state with typo hint. Message wording must not reveal whether the email exists.
- State C (2FA code): h2 "Enter your code", sentence "Open your authenticator app and type the 6-digit code for StoreCart.", single code field (5.8), hint "The code changes every 30 seconds.", Verify and sign in (accent), links Use a backup code and Back to sign in. Error variant: "That code did not work. Check the time on your device and try the next code." Locked variant after 5 attempts with a retry time.
- Loading: button shows spinner and "Signing in...", fields disabled but not greyed beyond 55%.

### 6.5 Admin users list (spec only; not on the concept board)

Same shell with the Admin label. Page header: h1 "Users", right actions Export (outline). Toolbar: search input (44px, magnifier icon, label "Search users by name or email"), filters Plan (select), Status (select), result count. Table columns: User (avatar initials + name + email), Plan (pill), Status (pill), Last sign-in (relative + absolute on hover/focus), Joined, row menu. Default sort Joined descending, `aria-sort`. 25 rows per page with pagination. Bulk actions are not in scope. Phone: stacked rows with name, plan and status; actions in the row menu. This replaces the existing unstyled table in `src/app/(admin)/admin/users/page.tsx`.

---

## 7. Content-state tables

Legend: Loading, Empty, Error, Partial, Success, Permission.

### Landing
| State | Treatment |
|---|---|
| Loading | Static page; no spinner. Web fonts use `swap` with the Georgia fallback so layout does not jump (size-adjusted) |
| Empty | n/a |
| Error | n/a. If live plan prices fail to load, hide price numbers in the teaser and link to Pricing |
| Partial | Illustration is static example data, captioned as such |
| Success | n/a |
| Permission | Signed-in visitors see "Open workspace" in place of Start free and Sign in |

### Merchant dashboard
| State | Treatment |
|---|---|
| Loading | Shell and header render immediately; each KPI cell, the table and plan usage show their own skeletons (no full-page spinner); skeletons do not animate under reduced motion |
| Empty (new store) | KPI values show a dash with "No sales yet"; orders panel replaced by a three-step checklist (Add a product, Connect Stripe, Add a domain) with one accent button; attention list says "Nothing needs attention" |
| Error | Per-panel inline error ("Could not load orders", Retry button, `role="alert"` on first appearance); a full-page error only if the session fails (existing `error.tsx`) |
| Partial | Panels fail independently; KPI delta omitted when the previous period has no data ("No comparison yet") |
| Success | Normal view; toast for actions such as product added (existing toast provider) |
| Permission | Staff roles hide Plan and billing and Domains from the nav; a direct visit shows "You do not have access. Ask the owner (name) for the role" with a link back to Overview. Unverified email redirects to verify (existing behaviour) |

### Pricing
| State | Treatment |
|---|---|
| Loading | Plan cards render with limits; price areas show skeleton (space reserved) |
| Empty | n/a |
| Error | Prices unavailable: show "Contact us" for paid plans instead of $0 (today's `FALLBACK_PRICES` shows 0, `subscriptions.ts:36-39`); checkout failure is an inline alert under the CTA |
| Partial | Yearly price missing: hide the Yearly option and say why |
| Success | After checkout the dashboard shows the success handler (existing) |
| Permission | Current plan CTA is "Current plan" (disabled); downgrade routes to billing settings; signed-out visitors go to sign-up with plan preselected |

### Sign-in
| State | Treatment |
|---|---|
| Loading | Button loading state (5.1); fields stay readable; double submit prevented |
| Empty | Initial state; no validation until submit or blur |
| Error | Alert panel plus field errors (6.4); network error: "We could not reach StoreCart. Check your connection and try again." |
| Partial | n/a |
| Success | Redirect to workspace; for 2FA users, move to the code state, focus the code field |
| Permission | Unverified email: redirect to verify (existing); disabled account: "This account is suspended. Contact support." with a mail link; rate limited: states the wait time |

### Admin users list
| State | Treatment |
|---|---|
| Loading | Table header visible, 8 skeleton rows |
| Empty | No users: "No users yet". No results: "No users match 'x'" with a Clear filters button |
| Error | Inline alert above the table with Retry; toolbar remains usable |
| Partial | Rows with missing profile data show "Not set" in muted text |
| Success | Row action confirmations via toast; destructive actions need a confirm dialog naming the user |
| Permission | Non-admins are redirected away; admin without a specific right sees the action disabled with a tooltip reason, not hidden |

---

## 8. Implementation phasing (maps to small Jira stories)

Story keys are placeholders for the owner to create; per `CLAUDE.md` each starts To-do and its acceptance criteria (AC) are its definition of done. Other developers are editing `nextjs-frontend/src` now, so Phase 0 should land first and small to avoid conflicts. Everything uses existing components (`src/components/ui/*`) and CSS tokens; no new dependencies. Data-backed screens (dashboard KPIs, orders, admin) are built against typed props and the empty/loading states so they can be re-pointed at the FastAPI backend later.

### Phase 0: Contrast, tokens, font (do first)

**P0.1 Fix contrast tokens and add a CTA button variant** (risk: medium; touches visuals everywhere and theme presets)
- AC: (1) `--cta`, `--cta-foreground`, `--cta-hover`, `--accent-ink`, status pairs, `--feature` exist in `globals.css` and in `ThemeModeVariables` and both presets in `themes.ts`; (2) `--muted-foreground`, `--input`, `--ring`, `--destructive` updated as in section 4; (3) `Button` has an `accent` variant using `--cta`; all 14 `bg-theme-accent text-white` occurrences replaced; (4) a Vitest test computes contrast for every documented pair in both themes and both presets and asserts the AA thresholds; (5) `npm run lint`, `typecheck`, `test:unit` pass.
- Files: `src/app/globals.css`, `src/config/themes.ts`, `tailwind.config.ts`, `src/components/ui/button.tsx`, `src/components/ui/badge.tsx` (focus classes), the 11 files in finding F1, new `src/__tests__/unit/theme-contrast.test.ts`.
- Risk notes: existing snapshot or e2e tests that select by class; admin theme settings page previews. Land before other UI stories.

**P0.2 Define the display font token** (risk: low)
- AC: (1) `Fraunces` loaded in `fonts.ts` with `variable: '--font-display'` and applied on `<body>` in `layout.tsx` independent of the admin body-font choice; (2) h1-h3 render Fraunces; admin font setting still changes body only; (3) fallback Georgia unchanged; (4) no layout shift above 0.1 CLS on landing; font files subset to latin; (5) build passes.
- Files: `src/config/fonts.ts`, `src/app/layout.tsx`; `tailwind.config.ts` needs no change (it already references `--font-display`).

**P0.3 Touch targets and focus ring** (risk: medium; changes control sizes)
- AC: (1) Button sizes 48/44/40/44 and Input 44 (already `h-11`); (2) one focus style: 3px outline, 2px offset, `--ring`; remove `ring-1` and `ring-ring/50`; gold ring on inverse surfaces; (3) every interactive element in dashboard, auth and pricing is at least 44px, or at least 24px if inline text; checked with a Playwright test of bounding boxes; (4) keyboard walkthrough of login and pricing recorded in the PR.
- Files: `src/components/ui/button.tsx`, `src/components/ui/input.tsx`, `src/app/globals.css:129-131`, `src/components/ui/badge.tsx`, `src/components/pricing/billing-toggle.tsx`.

**P0.4 Motion hygiene** (risk: low)
- AC: reduced-motion media query disables reveal, shimmer and transitions; `.stagger-children` children are visible without animation when reduced; gold glow hovers removed from `.theme-card` and `.theme-border`; reveal travel 10px.
- Files: `src/app/globals.css`.

### Phase 1: Merchant shell and shared components

**P1.1 Sidebar shell and mobile tab bar for `/dashboard`** (risk: medium; layout of every dashboard page)
- AC: sidebar at container width 900px and up with the items in 5.2; bottom tab bar below with a More sheet; `aria-current`, landmarks, skip link; all current dashboard routes still reachable on a 375px viewport; e2e test navigates every route at 375 and 1440.
- Files: `src/app/dashboard/layout.tsx`, `src/components/dashboard/dashboard-header.tsx`, new `src/components/dashboard/sidebar.tsx`, `tab-bar.tsx`.
- Depends on P0.1, P0.3.

**P1.2 Status pill, KPI strip and table components** (risk: low)
- AC: `StatusPill` (variants good/warn/crit/info/neutral with icon + text), `KpiStrip`, `DataTable` styles per section 5 with loading/empty/error variants; Vitest tests for each variant including accessible names; Storybook is not required.
- Files: new `src/components/ui/status-pill.tsx`, `src/components/dashboard/kpi-strip.tsx`, adjustments to `src/components/ui/table.tsx`.

**P1.3 Merchant Overview page** (risk: medium; data source is not yet the merchant backend)
- AC: page layout per 6.2 with props typed so the FastAPI contract can be plugged in; empty (new store), loading, error, permission states from section 7 implemented with fixtures; account info, login history and notifications moved to Settings pages (links preserved); no `theme-card` inside another card.
- Files: `src/app/dashboard/page.tsx`, `src/app/dashboard/settings/*`, new components.
- Depends on P1.1, P1.2. Open question about which backend data is available (section 11).

### Phase 2: Landing

**P2.1 Replace boilerplate landing content** (risk: low; marketing copy needs owner approval)
- AC: no references to Next.js, React, TypeScript, boilerplate or `github.com/yourusername` remain on `/`; hero, steps, product proof and CTA band per 6.1 with owner-approved copy; metadata title and description updated (`src/config/site.ts`); no `bg-theme-accent text-white`; Lighthouse accessibility 95 or higher; no horizontal scroll at 375.
- Files: `src/app/page.tsx`, `src/config/site.ts`, `src/app/layout.tsx` (author/creator "Your Name" placeholders at lines 27-31, 53 are also boilerplate).

### Phase 3: Pricing

**P3.1 Plan card redesign with limits** (risk: medium; depends on plan limits config)
- AC: plan card per 5.6 with stores/products/staff limits from the plans config (placeholder "Example:" feature strings removed); featured plan has no scale transform; price skeleton and "Contact us" fallback replace `$0` fallback; checkout error is inline `role="alert"`, not `alert()`.
- Files: `src/components/pricing/pricing-card.tsx`, `src/config/subscriptions.ts`, `src/app/pricing/page.tsx`.
- Depends on the plan-limits story (KAN-42 merged "subscription plans config with limits").

**P3.2 Billing toggle as radiogroup** (risk: low)
- AC: `role="radiogroup"`, arrow-key support, 44px targets, foreground-fill selected state, "save N%" computed from real prices.
- Files: `src/components/pricing/billing-toggle.tsx`.

### Phase 4: Auth

**P4.1 Sign-in and sign-up form states** (risk: low)
- AC: form-level alert with `role="alert"`; field errors linked by `aria-describedby`; focus management on submit; loading label; copy per 6.4 that does not reveal account existence; same for signup and reset-password.
- Files: `src/components/auth/login-form.tsx`, `signup-form.tsx`, `src/app/(auth)/*`.

**P4.2 Two-factor code step in sign-in** (risk: high; blocked on the auth architecture decision)
- AC: second state per 6.4 including backup code, error and lockout variants; single `one-time-code` input; works with the chosen auth provider.
- Files: `login-form.tsx`, a new `two-factor-step.tsx`.
- Blocked: today there is no 2FA code step at sign-in (`login-form.tsx`), and the backend is moving to FastAPI; do not start until the owner decides where MFA is verified.

### Phase 5: Admin

**P5.1 Admin users list** (risk: medium; reads Prisma today, to be re-pointed later)
- AC: layout per 6.5: search, filters, status pills, `aria-sort`, pagination, empty and error states, stacked rows at phone width; keeps the existing data function.
- Files: `src/app/(admin)/admin/users/page.tsx`, shared table components from P1.2.

### Phase 6: Quality gates

**P6.1 Visual regression and accessibility checks** (risk: low)
- AC: Playwright screenshots of Landing, Dashboard, Pricing, Sign-in at 375, 768, 1440 in light and dark; axe-core run on those four pages with zero serious or critical violations; reduced-motion test.
- Files: `src/__tests__/e2e/*`, `playwright.config.ts`.

Suggested sequence: P0.1, P0.2, P0.3, P0.4 (parallelisable after P0.1), then P1.1, P1.2, P1.3, P2.1, P3.1, P3.2, P4.1, P5.1, P6.1, with P4.2 whenever the auth decision is made. Each phase can ship independently; Phase 0 alone removes every WCAG contrast failure found.

---

## 9. Accessibility and responsive checklist (per screen, before merge)

- [ ] Every text and icon pair meets 4.5:1 (3:1 for large text and non-text UI) in light, dark and the `plain` preset; verified by the contrast test.
- [ ] Interactive targets are at least 44px (24px only for inline sentence links); no two targets closer than 8px.
- [ ] Visible focus on every interactive element with at least 3:1 against its background, including on inverse panels; logical tab order; skip link present.
- [ ] Landmarks: one `<header>`/nav, `<main>`, `<aside>` where present; one `h1` per page; heading levels do not skip.
- [ ] Status, errors and deltas use icon + text, not colour only; error alerts use `role="alert"`; field errors use `aria-describedby` and `aria-invalid`.
- [ ] Current page marked with `aria-current="page"`; toggles use `aria-checked` or `aria-pressed` correctly.
- [ ] Tables have captions and `scope`; stacked mobile tables preserve reading order.
- [ ] `prefers-reduced-motion: reduce` removes reveal, shimmer and non-essential transitions; no content hidden at `opacity: 0` without animation.
- [ ] Text can be resized to 200% and zoomed to 400% (320px) with no horizontal scroll or loss of content; no fixed heights that clip text.
- [ ] No horizontal page scroll at 375, 768, 1440; layouts verified at 375x812, 768x1024, 1440x900.
- [ ] Both themes reviewed on real screens; `color-scheme` set so form controls and scrollbars match.
- [ ] Images and illustrations have alt text or are marked decorative; example-data illustrations carry a caption.
- [ ] Fonts: max two families, `display: swap`, latin subset; headings do not shift layout by more than 0.1 CLS.
- [ ] Core Web Vitals targets from the web performance rules: LCP < 2.5s, INP < 200ms, CLS < 0.1.

---

## 10. Verification record (what was and was not checked)

Checked:
- All contrast ratios in section 4.3 were computed with a Node script using the WCAG 2.2 relative-luminance formula on the HSL tokens above. The HSL-to-hex conversions are in the tables.
- The HTML concept board was opened in the built-in browser. Layout, no horizontal overflow (document scroll width equal to client width) and visuals were inspected at: 375x812 light (dashboard section), 375x812 dark (sign-in error state), a 1440 viewport request dark (landing hero and pricing; the pane is narrower than 1440, so the frames rendered at about 1146px of content width), and a roughly 1037px light render (dashboard with sidebar). A measured pass at 375 found no overflowing elements.
- Fixes made because of what was seen: featured plan had no separation from other plans in dark mode (added a distinct `--feature` surface and gold border); sticky board header covered most of the phone screen (made static below 700px); footer and table links under 44px (raised to 44px).
- Google Fonts (Fraunces, Inter) loaded in the browser pane.

Not verified:
- 768x1024 was not rendered. A true 1440-wide render in both themes was not captured (the pane limited the effective width), so the two-column dashboard grid at container width 1000px and above and the full wide landing hero in light mode were not seen at that width.
- The 2FA frame and the bottom tab bar were built but not individually screenshotted; keyboard focus rings and hover states were not exercised in a real browser session. Screen-reader behaviour (NVDA, VoiceOver) was not tested.
- Nothing in `nextjs-frontend` was run or changed, so none of the proposed token changes were tried against the real components or test suite.
- The `plain` preset values and the Fraunces rendering within `next/font` (axes option) are based on reading the code and docs, not on a build.
- No Figma file exists; the frame specs have not been built or reviewed visually in Figma.

---

## 11. Open questions for the owner

1. **Brand direction.** Do you confirm "Ledger and Brass" (ivory, navy, brass, serif headings, hairline panels) as the direction, keeping the existing gold and navy identity?
2. **Display font.** Is Fraunces acceptable, or would you prefer Newsreader, Source Serif 4 or Instrument Serif? Should the body font stay admin-selectable from the current ten fonts (this plan assumes yes and only fixes the display font)?
3. **Example data.** Please confirm that every name, price, plan limit and figure in the mockups ($29 Pro, $24 yearly, 1/3/unlimited stores, 50/2,500 products, 3/10/50+ staff, 17% yearly saving, revenue figures) is an example only. What are the real plan limits and prices, and should Enterprise show "Custom"?
4. **Admin themes.** Is the admin-selectable theme preset system (`luxury`, `plain`) staying? This plan adds `--cta` pairs so each preset stays accessible. If only `luxury` will remain, Phase 0 gets simpler.
5. **Dashboard scope.** Which merchant data will the FastAPI backend expose first (orders, products, customers, revenue)? KPI strip and orders table need it; until then Phase 1.3 would show empty states. Should account pages (profile, security, login history) move under Settings as proposed?
6. **Two-factor sign-in.** Where is the second factor verified once the backend moves to FastAPI (Firebase MFA or the new service)? P4.2 stays blocked until this is decided.
7. **Landing copy and claims.** The headline, steps and "No card needed for the Free plan" are proposals. Are they accurate for the product (custom domains, Stripe, staff roles, CSV import) and approved for use?
8. **Figma.** Who will build the Figma file from this spec, and should the concept board be kept in the repo as a design reference or removed once Figma exists?
9. **Sizes.** Is a 44px default control height acceptable across dense admin tables, or should dense desktop tables use the 40px `sm` size (meets the 24px AA floor but not the 44px target rule)?

