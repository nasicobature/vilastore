# VilaStore AI Coding Workflow

This backend repo uses a safe branch workflow for Codex tasks. The main branch must stay stable and should only receive reviewed changes.

## Repositories

- Backend: `VilaStore` - Django backend, web views, APIs, payments, school portal, shop and house management.
- Mobile: `VilaStoreMobile` - React Native mobile app, scanner flow, marketplace screens, owner and staff mobile dashboards.

## Branches

Use one branch per task area:

- `codex/shop-management`
- `codex/house-management`
- `codex/mobile-scanner`
- `codex/marketplace-ui`
- `codex/bug-fixes`

Use `codex/ai-coding-workflow` only for workflow documentation and setup.

## Safe Rule

Codex must not push directly to `main`.

Codex should:

1. Start from the right `codex/*` branch.
2. Make only changes related to that task.
3. Run checks/tests before committing.
4. Push the task branch, not `main`.
5. Wait for human review before merging.

## Starting A Task

Backend example:

```bash
cd C:\Users\HomePC\Desktop\VilaStoreProject\VilaStore
git switch codex/shop-management
git pull origin main
```

Mobile example:

```bash
cd C:\Users\HomePC\Desktop\VilaStoreProject\VilaStoreMobile
git switch codex/mobile-scanner
git pull origin main
```

If the branch has already been pushed before, use:

```bash
git pull origin codex/shop-management
```

## Running Multiple Codex Sessions With tmux

Create one tmux session per task:

```bash
tmux new -s shop-management
tmux new -s house-management
tmux new -s mobile-scanner
tmux new -s marketplace-ui
tmux new -s bug-fixes
```

Detach from a session:

```bash
Ctrl+b then d
```

List sessions:

```bash
tmux ls
```

Return to a session:

```bash
tmux attach -t shop-management
```

Inside each tmux session, switch to the matching branch before asking Codex to work.

## Suggested Branch Mapping

- Shop dashboard, inventory, reports, staff, payments: `codex/shop-management`
- Rentals, tenants, agents, house listings: `codex/house-management`
- Barcode scanning, cart, offline sales, mobile checkout: `codex/mobile-scanner`
- Marketplace search, shop cards, house cards, filters: `codex/marketplace-ui`
- Login, registration, 500 errors, payment errors, tests: `codex/bug-fixes`

## Before Pushing

Backend:

```bash
python manage.py check
python manage.py test
```

Mobile:

```bash
npm test
npx expo-doctor
```

If a full test command is too slow or unavailable, run the focused check for the files changed and mention what was not run.

