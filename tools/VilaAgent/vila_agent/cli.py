import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from .model import ask_model
from .project import build_context, ensure_agent_dir, init_rules, read_rules
from .safety import ensure_safe_branch, git_branch, git_status


def run_command(command, cwd):
    result = subprocess.run(
        command,
        cwd=str(cwd),
        shell=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.returncode, result.stdout


def write_outputs(repo, response):
    agent_dir = ensure_agent_dir(repo)
    response_path = agent_dir / "last_response.json"
    patch_path = agent_dir / "last_patch.diff"
    response_path.write_text(json.dumps(response, indent=2), encoding="utf-8")
    patch = response.get("unified_diff", "") or ""
    patch_path.write_text(patch, encoding="utf-8")
    return response_path, patch_path


def apply_patch(repo, patch_path):
    if not patch_path.exists() or not patch_path.read_text(encoding="utf-8").strip():
        return False, "No patch was generated."
    check = subprocess.run(
        ["git", "apply", "--check", str(patch_path)],
        cwd=str(repo),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if check.returncode != 0:
        return False, check.stdout
    apply = subprocess.run(
        ["git", "apply", str(patch_path)],
        cwd=str(repo),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return apply.returncode == 0, apply.stdout


def command_doctor(args):
    repo = Path(args.repo).resolve()
    print(f"Repo: {repo}")
    print(f"Branch: {git_branch(repo)}")
    print("Git status:")
    print(git_status(repo) or "clean")
    print("Rules file:", "found" if (repo / "AGENT_RULES.md").exists() else "not found")


def command_init(args):
    repo = Path(args.repo).resolve()
    path = init_rules(repo)
    print(f"Created or kept rules file: {path}")


def command_task(args):
    repo = Path(args.repo).resolve()
    if not repo.exists():
        raise SystemExit(f"Repo not found: {repo}")

    current_branch = git_branch(repo)
    if args.branch and current_branch != args.branch:
        print(f"Switching branch: {args.branch}")
        code, output = run_command(f"git switch {args.branch}", repo)
        if code != 0:
            raise SystemExit(output)
        current_branch = git_branch(repo)

    ensure_safe_branch(current_branch, allow_main=args.allow_main)

    rules = read_rules(repo)
    context = build_context(repo, args.task, rules, max_files=args.max_files)
    agent_dir = ensure_agent_dir(repo)
    context_path = agent_dir / "last_context.txt"
    context_path.write_text(context, encoding="utf-8")

    print(f"Repo: {repo}")
    print(f"Branch: {current_branch}")
    print(f"Context saved: {context_path}")
    print("Asking AI model...")

    response = ask_model(
        task=args.task,
        context=context,
        model=args.model or os.getenv("VILA_AGENT_MODEL", "gpt-5.2"),
    )
    response_path, patch_path = write_outputs(repo, response)

    print(f"Response saved: {response_path}")
    print(f"Patch saved: {patch_path}")
    print()
    print("Plan:")
    print(response.get("plan", "No plan returned."))
    print()
    print("Summary:")
    print(response.get("summary", "No summary returned."))

    if args.apply:
        print()
        print("Applying patch...")
        ok, output = apply_patch(repo, patch_path)
        if not ok:
            raise SystemExit(f"Patch failed:\n{output}")
        print(output or "Patch applied.")

        for test_command in args.test:
            print()
            print(f"Running test: {test_command}")
            code, test_output = run_command(test_command, repo)
            print(test_output)
            if code != 0:
                raise SystemExit(f"Test failed: {test_command}")
    else:
        print()
        print("Patch was not applied. Re-run with --apply after review.")


def build_parser():
    parser = argparse.ArgumentParser(prog="vila-agent", description="Small safe terminal coding agent.")
    parser.add_argument("task", nargs="?", help="Coding task to perform.")
    parser.add_argument("--repo", default=".", help="Target repo path.")
    parser.add_argument("--branch", default="", help="Branch to switch to before work.")
    parser.add_argument("--model", default="", help="AI model name.")
    parser.add_argument("--apply", action="store_true", help="Apply generated unified diff.")
    parser.add_argument("--allow-main", action="store_true", help="Allow working on main/master.")
    parser.add_argument("--max-files", type=int, default=350, help="Maximum file paths in context.")
    parser.add_argument("--test", action="append", default=[], help="Test command to run after applying. Can be repeated.")

    return parser


def main():
    if len(sys.argv) > 1 and sys.argv[1] in {"doctor", "init"}:
        command = sys.argv[1]
        subparser = argparse.ArgumentParser(prog=f"vila-agent {command}")
        subparser.add_argument("--repo", default=".")
        args = subparser.parse_args(sys.argv[2:])
        if command == "doctor":
            command_doctor(args)
        else:
            command_init(args)
        return

    parser = build_parser()
    args = parser.parse_args()
    if not args.task:
        parser.print_help()
        sys.exit(1)
    command_task(args)
