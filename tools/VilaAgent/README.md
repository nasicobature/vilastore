# VilaAgent

VilaAgent is a small local coding agent you can run inside your terminal.

It is built for VilaStore-style projects with a Django backend and React Native mobile frontend, but it can work on any Git repo.

## What It Does

- Reads project rules.
- Checks the current Git branch.
- Refuses to work on `main` by default.
- Collects a small file tree and Git status.
- Sends your task to a big AI model when `OPENAI_API_KEY` is configured.
- Saves the AI plan and patch suggestion.
- Applies the patch only when you use `--apply`.
- Runs optional test commands after applying.

## Quick Start

From this folder:

```bat
python -m vila_agent "Fix login issue" --repo ..\VilaStore --branch codex/bug-fixes
```

Apply the generated patch:

```bat
python -m vila_agent "Fix login issue" --repo ..\VilaStore --branch codex/bug-fixes --apply
```

Run tests after applying:

```bat
python -m vila_agent "Fix login issue" --repo ..\VilaStore --branch codex/bug-fixes --apply --test "python manage.py check"
```

## Environment

Set your OpenAI API key:

```bat
setx OPENAI_API_KEY "your_key_here"
```

Optional model:

```bat
setx VILA_AGENT_MODEL "gpt-5.2"
```

Restart your terminal after `setx`.

## Safe Branch Rule

VilaAgent refuses to work on:

```text
main
master
production
prod
```

unless you pass:

```bat
--allow-main
```

Use your safe branches:

```text
codex/bug-fixes
codex/shop-management
codex/house-management
codex/mobile-scanner
codex/marketplace-ui
```

## Files Created

Inside the repo you run it against, VilaAgent creates:

```text
.vila-agent/
  last_context.txt
  last_response.json
  last_patch.diff
  logs/
```

## Commands

Show repo safety info:

```bat
python -m vila_agent doctor --repo ..\VilaStore
```

Create default agent rules in a repo:

```bat
python -m vila_agent init --repo ..\VilaStore
```

