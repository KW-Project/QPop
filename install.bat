@echo off
cd /d "%~dp0"
python -m pip install --user --quiet pystray pillow qrcode
python qpop.py --install
pause
