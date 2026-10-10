@echo off
rem Builds EPFL-Moodle-Downloader.exe. Needs Python 3.10+ from python.org.
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv 2>nul || python -m venv .venv
)
call .venv\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip || goto :error
pip install -r requirements.txt pyinstaller || goto :error
pyinstaller --noconfirm --onefile --console --name "EPFL-Moodle-Downloader" ^
  --collect-all playwright --collect-submodules yt_dlp --collect-all yt_dlp_ejs --collect-all imageio_ffmpeg ^
  --hidden-import keyring.backends.Windows run.py || goto :error
copy /y dist\EPFL-Moodle-Downloader.exe . >nul
echo.
echo Built: %~dp0EPFL-Moodle-Downloader.exe
exit /b 0
:error
echo Build failed.
exit /b 1
