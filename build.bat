@echo off
rem Builds the QPop installer: dist\QPop-Setup-<version>.exe
rem Needs Python and Inno Setup 6 (winget install JRSoftware.InnoSetup).
setlocal
cd /d "%~dp0"

python -m pip install --user --quiet -r requirements.txt pyinstaller || goto :error

rem Icon, exe file properties and version string, all generated from qpop.py.
python packaging\build_assets.py || goto :error
set /p VERSION=<build\version.txt

rem One folder (not one file): starts faster and trips antivirus less often.
rem pystray picks its backend at runtime, so PyInstaller can't see it - include it explicitly.
python -m PyInstaller --noconfirm --clean --onedir --windowed ^
    --name QPop ^
    --icon build\icon.ico ^
    --version-file build\version_info.txt ^
    --hidden-import pystray._win32 ^
    qpop.py || goto :error

set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo Inno Setup 6 not found. Install it with: winget install JRSoftware.InnoSetup
    goto :error
)
"%ISCC%" /Q /DAppVersion=%VERSION% packaging\QPop.iss || goto :error

echo.
echo Built dist\QPop-Setup-%VERSION%.exe
goto :eof

:error
echo.
echo Build failed.
exit /b 1
