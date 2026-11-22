@echo off
setlocal
cd /d "%~dp0"

python -m PyInstaller ^
  --onefile ^
  --name "VORTEX CLONER" ^
  --clean ^
  --noconfirm ^
  --hidden-import=colorama ^
  --distpath dist ^
  --workpath build_pyi ^
  --specpath . ^
  vortex_main.py

if errorlevel 1 (
  echo build failed
  exit /b 1
)

set "SRC=dist\VORTEX CLONER.exe"
set "DST=VORTEX CLONER.exe"
set /a TRY=0

:copyloop
set /a TRY+=1
copy /Y "%SRC%" "%DST%" >nul 2>&1
if not errorlevel 1 goto copied
if %TRY% GEQ 5 (
  echo could not replace %DST% - close it and copy from dist
  exit /b 1
)
timeout /t 2 /nobreak >nul
goto copyloop

:copied
echo built: VORTEX CLONER.exe
endlocal
