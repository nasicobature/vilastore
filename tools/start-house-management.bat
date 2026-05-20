@echo off
setlocal
set "ROOT=%~dp0"
set "BRANCH=codex/house-management"
set "TASK=House management: listings, rentals, tenants, agents, house manager dashboard, and rent payment tracking."
call "%ROOT%start-codex-task.bat" "%BRANCH%" "%TASK%"

