@echo off
setlocal
set "ROOT=%~dp0"
set "BRANCH=codex/shop-management"
set "TASK=Shop management: dashboard, inventory, reports, staff tools, subscription limits, receipt printing, and payment flow."
call "%ROOT%start-codex-task.bat" "%BRANCH%" "%TASK%"

