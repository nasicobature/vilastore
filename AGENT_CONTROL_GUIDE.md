# VilaStore AI Coding Agent Control Guide

This guide explains how to run separate Codex coding sessions for VilaStore without damaging `main`.

## Main Safety Rule

Do not work directly on `main`.

Use these branches only:

- `codex/bug-fixes`
- `codex/shop-management`
- `codex/house-management`
- `codex/mobile-scanner`
- `codex/marketplace-ui`

Codex should push task branches only. You review before merging into `main`.

## Project Folders

Backend:

```bat
C:\Users\HomePC\Desktop\VilaStoreProject\VilaStore
```

Mobile:

```bat
C:\Users\HomePC\Desktop\VilaStoreProject\VilaStoreMobile
```

## Branch Purposes

### `codex/bug-fixes`

Use for:

- login/register fixes
- server 500 errors
- payment errors
- product update bugs
- dashboard data not showing
- urgent repair work

### `codex/shop-management`

Use for:

- shop dashboard
- inventory
- reports and business analysis
- staff/shopboy tools
- subscription feature limits
- receipt/slip printing

### `codex/house-management`

Use for:

- house listings
- rental management
- tenants
- agents
- house manager dashboards

### `codex/mobile-scanner`

Use for:

- mobile barcode scanner
- scan to cart
- pending payment orders
- staff payment confirmation
- mobile offline scanner flow

### `codex/marketplace-ui`

Use for:

- marketplace shop cards
- house/rental cards
- search and filters
- mobile marketplace layout
- empty/loading/error states

## Start A Codex Session Manually

Backend example:

```bat
cd /d C:\Users\HomePC\Desktop\VilaStoreProject\VilaStore
git switch codex/bug-fixes
codex
```

Mobile example:

```bat
cd /d C:\Users\HomePC\Desktop\VilaStoreProject\VilaStoreMobile
git switch codex/mobile-scanner
codex
```

Inside Codex, start with a clear instruction:

```text
Work only on this branch. Do not push to main. Do not delete existing features.
```

## Start With Windows Scripts

From:

```bat
C:\Users\HomePC\Desktop\VilaStoreProject
```

Run one of these:

```bat
start-bug-fixes.bat
start-shop-management.bat
start-house-management.bat
start-mobile-scanner.bat
start-marketplace-ui.bat
```

Tracked copies are also stored in the backend repo under:

```bat
C:\Users\HomePC\Desktop\VilaStoreProject\VilaStore\tools
```

You can run them from there too.

Each script opens two terminals:

- one for backend
- one for mobile

Each terminal switches to the matching branch and starts Codex with an instruction file.

## Testing

Backend tests:

```bat
cd /d C:\Users\HomePC\Desktop\VilaStoreProject\VilaStore
python manage.py check
python manage.py test
```

Mobile checks:

```bat
cd /d C:\Users\HomePC\Desktop\VilaStoreProject\VilaStoreMobile
npm test
npx expo-doctor
```

If full tests are slow, run focused checks for the files changed and mention what was not run.

## Commit

Check files first:

```bat
git status --short
```

Commit only the task changes:

```bat
git add path\to\changed-file
git commit -m "Fix login registration flow"
```

## Push

Push the task branch only:

```bat
git push origin codex/bug-fixes
```

Never push directly to `main`.

## Review Before Merge

1. Open GitHub.
2. Compare the task branch with `main`.
3. Review changed files.
4. Confirm tests passed.
5. Merge only after review.
6. Deploy after merge if needed.

## Parallel Work

You can run multiple scripts at the same time, but avoid editing the same files in two branches.

Good parallel split:

- `codex/bug-fixes`: backend login/payment repair
- `codex/mobile-scanner`: mobile scanner UI
- `codex/marketplace-ui`: marketplace design

Risky parallel split:

- two branches both editing `core/api.py`
- two branches both editing `App.js`
- two branches both editing login screens
