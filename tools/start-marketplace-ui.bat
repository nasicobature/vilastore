@echo off
setlocal
set "ROOT=%~dp0"
set "BRANCH=codex/marketplace-ui"
set "TASK=Marketplace UI: shop cards, house/rental cards, search, filters, loading states, empty states, and mobile-friendly layout."
call "%ROOT%start-codex-task.bat" "%BRANCH%" "%TASK%"

