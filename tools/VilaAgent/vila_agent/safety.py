import subprocess

PROTECTED_BRANCHES = {"main", "master", "production", "prod"}


def git_branch(repo):
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=str(repo),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.stdout.strip()


def git_status(repo):
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=str(repo),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.stdout.strip()


def ensure_safe_branch(branch, allow_main=False):
    if branch in PROTECTED_BRANCHES and not allow_main:
        raise SystemExit(
            f"Refusing to work on protected branch '{branch}'. "
            "Switch to a codex/* branch or pass --allow-main."
        )

