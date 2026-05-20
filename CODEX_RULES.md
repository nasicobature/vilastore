# Codex Rules For VilaStore

1. Do not push directly to `main`.
2. Work only in `codex/*` task branches unless the user explicitly says otherwise.
3. Do not delete existing features without explicit approval.
4. Do not revert user changes unless the user asks for that exact revert.
5. Keep each branch focused on one task area.
6. Run checks/tests before committing when possible.
7. Push task branches for review, not `main`.
8. Mention any tests that could not be run.
9. Keep backend and mobile changes coordinated but commit them in their own repos.
10. Never commit secrets, API keys, signing keys, or local build artifacts.

## Protected Branch

`main` is the stable branch. It should only receive reviewed and approved merges.

## Task Branches

- `codex/shop-management`
- `codex/house-management`
- `codex/mobile-scanner`
- `codex/marketplace-ui`
- `codex/bug-fixes`

