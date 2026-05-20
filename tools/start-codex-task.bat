@echo off
setlocal

set "BRANCH=%~1"
set "TASK=%~2"
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI\"
set "BACKEND=%ROOT%VilaStore"
set "MOBILE=%ROOT%VilaStoreMobile"

if "%BRANCH%"=="" (
  echo Missing branch name.
  pause
  exit /b 1
)

echo Starting VilaStore Codex task on %BRANCH%
echo.

if not exist "%BACKEND%\.git" (
  echo Backend repo not found: %BACKEND%
  pause
  exit /b 1
)

if not exist "%MOBILE%\.git" (
  echo Mobile repo not found: %MOBILE%
  pause
  exit /b 1
)

set "BACKEND_INSTRUCTION=%BACKEND%\CODEX_SESSION_INSTRUCTION.txt"
set "MOBILE_INSTRUCTION=%MOBILE%\CODEX_SESSION_INSTRUCTION.txt"

(
  echo You are Codex working on VilaStore backend.
  echo Branch: %BRANCH%
  echo Task: %TASK%
  echo Rules:
  echo - Do not push to main.
  echo - Do not delete existing features.
  echo - Keep changes focused on this task.
  echo - Run backend checks/tests before commit when possible.
  echo - Push only this branch for review.
) > "%BACKEND_INSTRUCTION%"

(
  echo You are Codex working on VilaStore mobile.
  echo Branch: %BRANCH%
  echo Task: %TASK%
  echo Rules:
  echo - Do not push to main.
  echo - Do not delete existing features.
  echo - Keep changes focused on this task.
  echo - Run mobile checks/tests before commit when possible.
  echo - Push only this branch for review.
) > "%MOBILE_INSTRUCTION%"

start "VilaStore Backend - %BRANCH%" /D "%BACKEND%" cmd /k "git switch %BRANCH% && echo Read CODEX_SESSION_INSTRUCTION.txt first. && where codex >nul 2>nul && codex || echo Codex CLI not found. Run: codex"

start "VilaStore Mobile - %BRANCH%" /D "%MOBILE%" cmd /k "git switch %BRANCH% && echo Read CODEX_SESSION_INSTRUCTION.txt first. && where codex >nul 2>nul && codex || echo Codex CLI not found. Run: codex"

echo Opened backend and mobile Codex terminals for %BRANCH%.
echo If a terminal says branch switch failed, check uncommitted changes with: git status --short
pause
