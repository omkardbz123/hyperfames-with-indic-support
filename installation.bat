@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title AI Video Studio - installation
cd /d "%~dp0"

echo.
echo  ================================================================
echo    AI Video Studio (HyperFrames + Marathi/Hindi)  -  installation
echo  ================================================================
echo.
echo  This checks your computer step by step and installs only what is
echo  missing. It ASKS before every install or download. You can run it
echo  again any time: finished steps are skipped.
echo.
echo  Full step-by-step guide with links: SETUP.md
echo  Needs: Windows 10/11 64-bit, internet, about 20 GB free disk.
echo.
pause

set "TOTAL=11"
set "PROBLEMS="
set "PATH=%USERPROFILE%\.local\bin;%PATH%"

rem ------------------------------------------------------------------ 1. basics
echo.
echo  [1/%TOTAL%] Windows, disk space and winget
set "FREEGB=999"
set "DRIVE=%~d0"
set "DRIVE=%DRIVE:~0,1%"
for /f %%f in ('powershell -NoProfile -Command "[math]::Floor((Get-PSDrive -Name '%DRIVE%').Free/1GB)"') do set "FREEGB=%%f"
echo     Free space on this drive: !FREEGB! GB
if !FREEGB! LSS 20 (
  echo     WARNING: less than 20 GB free. The models and tools need about 15-20 GB.
  set "PROBLEMS=!PROBLEMS! disk-space"
)
set "HAVE_WINGET=1"
where winget >nul 2>&1 || set "HAVE_WINGET="
if defined HAVE_WINGET (
  echo     winget: found
) else (
  echo     winget: NOT found. Installs below will show you a download link instead.
  echo     To get winget, install "App Installer" from the Microsoft Store:
  echo       https://apps.microsoft.com/detail/9NBLGGH4NNS1
)

rem ------------------------------------------------------------------ 2. git
echo.
echo  [2/%TOTAL%] Git  (needed to download one Python package and to get updates)
where git >nul 2>&1 && (
  for /f "delims=" %%v in ('git --version') do echo     found: %%v
  goto git_done
)
call :install "Git.Git" "Git" "https://git-scm.com/download/win"
where git >nul 2>&1 || set "PROBLEMS=!PROBLEMS! git"
:git_done

rem ------------------------------------------------------------------ 3. uv
echo.
echo  [3/%TOTAL%] uv  (installs Python 3.11 and the Python packages for this folder only)
where uv >nul 2>&1 && (
  for /f "delims=" %%v in ('uv --version') do echo     found: %%v
  goto uv_done
)
call :install "astral-sh.uv" "uv" "https://docs.astral.sh/uv/getting-started/installation/"
where uv >nul 2>&1 && goto uv_done
echo     Trying the official uv installer instead (from astral.sh)...
call :ask "    Run the official uv installer now"
if errorlevel 1 goto uv_fail
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
call :refresh_path
where uv >nul 2>&1 && goto uv_done
:uv_fail
set "PROBLEMS=!PROBLEMS! uv"
:uv_done

rem ------------------------------------------------------------------ 4. node
echo.
echo  [4/%TOTAL%] Node.js 22 or newer  (runs HyperFrames, the video renderer)
call :node_major
if !NODEMAJOR! GEQ 22 (
  echo     found: Node !NODEMAJOR!
  goto node_done
)
if !NODEMAJOR! GTR 0 echo     found Node !NODEMAJOR!, but HyperFrames needs 22 or newer.
call :install "OpenJS.NodeJS.LTS" "Node.js LTS" "https://nodejs.org/en/download"
call :node_major
if !NODEMAJOR! LSS 22 set "PROBLEMS=!PROBLEMS! node"
:node_done

rem ------------------------------------------------------------------ 5. ffmpeg
echo.
echo  [5/%TOTAL%] FFmpeg FULL build by Gyan  (video/audio engine; "essentials" builds lack filters we use)
call :have_ffmpeg
if defined FFMPEG_OK (
  echo     found: FFmpeg full build
  goto ffmpeg_done
)
call :install "Gyan.FFmpeg" "FFmpeg (Gyan full build)" "https://www.gyan.dev/ffmpeg/builds/  (get ffmpeg-release-full.7z, unzip into bin\ffmpeg\)"
call :have_ffmpeg
if not defined FFMPEG_OK set "PROBLEMS=!PROBLEMS! ffmpeg"
:ffmpeg_done

rem ------------------------------------------------------------------ 6. chrome
echo.
echo  [6/%TOTAL%] Google Chrome  (the review step measures on-screen text in Chrome)
call :have_chrome
if defined CHROME_OK (
  echo     found: Google Chrome
  goto chrome_done
)
call :install "Google.Chrome" "Google Chrome" "https://www.google.com/chrome/"
call :have_chrome
if not defined CHROME_OK set "PROBLEMS=!PROBLEMS! chrome"
:chrome_done

if not "!PROBLEMS!"=="" (
  echo.
  echo  Some programs are still missing:!PROBLEMS!
  echo  If you just installed them, CLOSE this window and run installation.bat again
  echo  ^(Windows only sees newly installed programs in a new window^).
  echo  Otherwise install them from the links above, then run this again.
  echo.
  where uv >nul 2>&1 || goto end_fail
  where node >nul 2>&1 || goto end_fail
)

rem ------------------------------------------------------------------ 7. python packages
echo.
echo  [7/%TOTAL%] Python 3.11 + Python packages  (about 3 GB, into .venv in this folder)
if exist ".venv\Scripts\python.exe" (
  echo     .venv exists; syncing it with pyproject.toml / uv.lock
) else (
  call :ask "    Download and install them now"
  if errorlevel 1 goto end_fail
)
uv sync
if errorlevel 1 (
  echo     uv sync FAILED. Check your internet connection and run installation.bat again.
  goto end_fail
)
rem scenedetect pulls plain opencv-python; the contrib build (saliency) must win
uv sync --reinstall-package opencv-contrib-python >nul
echo     Python packages OK

rem ------------------------------------------------------------------ 8. node packages
echo.
echo  [8/%TOTAL%] HyperFrames 0.8.172 and its Node packages  (about 300 MB, into node_modules)
if exist "node_modules\hyperframes\package.json" (
  echo     found: node_modules
) else (
  call npm ci
  if errorlevel 1 (
    echo     npm ci FAILED. Check your internet connection and run installation.bat again.
    goto end_fail
  )
)

rem ------------------------------------------------------------------ 9. tools + models
echo.
echo  [9/%TOTAL%] Studio tools and AI models  (asks before each download)
echo     Next: fonts, sound effects, slow-motion/upscale tools, speech models.
echo     The Marathi/Hindi model needs a free Hugging Face account: SETUP.md step 6.
uv run tools\setup.py
if errorlevel 1 set "PROBLEMS=!PROBLEMS! setup"

rem ------------------------------------------------------------------ 10. claude code
echo.
echo  [10/%TOTAL%] Claude Code  (the AI assistant you talk to; it runs every step for you)
where claude >nul 2>&1 && (
  for /f "delims=" %%v in ('claude --version 2^>nul') do echo     found: Claude Code %%v
  goto claude_done
)
echo     Not found. Claude Code needs a Claude account with a paid plan (Pro or Max).
echo     Options:
echo       a. Claude desktop app, "Code" tab:  https://claude.ai/download
echo       b. Command line:  https://docs.claude.com/en/docs/claude-code/setup
echo     Without it you can still run every tool by hand: uv run tools\^<tool^>.py --help
call :ask "    Install the Claude Code command line now (official installer from claude.ai)"
if errorlevel 1 goto claude_done
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://claude.ai/install.ps1 | iex"
call :refresh_path
:claude_done

rem ------------------------------------------------------------------ 11. doctor
echo.
echo  [11/%TOTAL%] Health check
uv run tools\doctor.py
echo.
echo  ================================================================
if "!PROBLEMS!"=="" (
  echo    Done. Open this folder in Claude Code and type:  /doctor
  echo    Then start a video:  /new-video my-first-video promo
) else (
  echo    Finished with items to fix:!PROBLEMS!
  echo    See the table above and SETUP.md ^(Troubleshooting^), then run
  echo    installation.bat again. Finished steps are skipped.
)
echo  ================================================================
echo.
pause
exit /b 0

:end_fail
echo.
echo  Installation stopped. Fix the item above and run installation.bat again.
pause
exit /b 1


rem ================================================================== helpers

:ask
rem  %1 = question. errorlevel 0 = yes, 1 = no
choice /c YN /m "%~1"
if errorlevel 2 exit /b 1
exit /b 0

:install
rem  %1 = winget id, %2 = name, %3 = manual download link
echo     %~2 is not installed.
echo     Manual download: %~3
if not defined HAVE_WINGET (
  echo     Install it from the link above, then run installation.bat again.
  exit /b 1
)
call :ask "    Install %~2 now with winget"
if errorlevel 1 exit /b 1
winget install --id %~1 -e --source winget --accept-package-agreements --accept-source-agreements
call :refresh_path
exit /b 0

:refresh_path
rem  Pick up programs installed a moment ago without opening a new window.
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')"`) do set "PATH=%USERPROFILE%\.local\bin;%%P"
exit /b 0

:node_major
set "NODEMAJOR=0"
for /f "delims=" %%v in ('node -p "parseInt(process.versions.node)" 2^>nul') do set "NODEMAJOR=%%v"
exit /b 0

:have_ffmpeg
set "FFMPEG_OK="
if exist "bin\ffmpeg\bin\ffmpeg.exe" set "FFMPEG_OK=1"
for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_*") do (
  for /d %%E in ("%%D\ffmpeg-*-full_build") do if exist "%%E\bin\ffmpeg.exe" set "FFMPEG_OK=1"
)
exit /b 0

:have_chrome
set "CHROME_OK="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME_OK=1"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME_OK=1"
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME_OK=1"
exit /b 0
