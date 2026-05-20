from pathlib import Path
import subprocess

DEFAULT_RULES = """# AGENT_RULES.md

1. Do not push directly to main.
2. Do not delete existing features without explicit approval.
3. Keep changes focused.
4. Run tests before commit when possible.
5. Never commit secrets.
"""

IGNORE_DIRS = {
    ".git",
    ".expo",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    ".vila-agent",
}

INTERESTING_FILES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".html",
    ".css",
    ".json",
    ".md",
    ".yaml",
    ".yml",
}


def ensure_agent_dir(repo):
    path = Path(repo) / ".vila-agent"
    path.mkdir(exist_ok=True)
    (path / "logs").mkdir(exist_ok=True)
    return path


def init_rules(repo):
    path = Path(repo) / "AGENT_RULES.md"
    if not path.exists():
        path.write_text(DEFAULT_RULES, encoding="utf-8")
    return path


def read_rules(repo):
    repo = Path(repo)
    candidates = [
        repo / "AGENT_RULES.md",
        repo / "CODEX_RULES.md",
        repo / "AI_CODING_WORKFLOW.md",
    ]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
    return DEFAULT_RULES


def list_files(repo, max_files=350):
    repo = Path(repo)
    results = []
    for path in repo.rglob("*"):
        if len(results) >= max_files:
            break
        if path.is_dir():
            continue
        rel = path.relative_to(repo)
        if any(part in IGNORE_DIRS for part in rel.parts):
            continue
        if path.suffix.lower() not in INTERESTING_FILES:
            continue
        results.append(str(rel))
    return results


def git_output(repo, args):
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
        )
        return result.stdout.strip()
    except Exception as exc:
        return str(exc)


def build_context(repo, task, rules, max_files=350):
    repo = Path(repo)
    files = list_files(repo, max_files=max_files)
    status = git_output(repo, ["status", "--short"])
    branch = git_output(repo, ["branch", "--show-current"])
    recent = git_output(repo, ["log", "-3", "--oneline"])

    context = [
        f"Task: {task}",
        f"Repo: {repo}",
        f"Branch: {branch}",
        "",
        "Rules:",
        rules,
        "",
        "Git status:",
        status or "clean",
        "",
        "Recent commits:",
        recent,
        "",
        f"Project files, limited to {max_files}:",
        "\n".join(files),
    ]
    return "\n".join(context)

