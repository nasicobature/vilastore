@echo off
setlocal
set "ROOT=%~dp0"
set "BRANCH=codex/mobile-scanner"
set "TASK=Mobile scanner: barcode scanning, scan to cart, pending payment orders, staff confirmation, and stock/report updates."
call "%ROOT%start-codex-task.bat" "%BRANCH%" "%TASK%"

