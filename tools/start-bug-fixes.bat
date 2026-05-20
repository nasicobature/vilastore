@echo off
setlocal
set "ROOT=%~dp0"
set "BRANCH=codex/bug-fixes"
set "TASK=Bug fixes: login/register issues, server errors, payment bugs, product update bugs, and dashboard data issues."
call "%ROOT%start-codex-task.bat" "%BRANCH%" "%TASK%"

