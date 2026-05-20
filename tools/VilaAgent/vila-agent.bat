@echo off
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"
python -m vila_agent %*
