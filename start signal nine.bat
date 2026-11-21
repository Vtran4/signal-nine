@echo off
cd /d "%~dp0"
start "" http://127.0.0.1:8139/
python -m http.server 8139 --bind 127.0.0.1