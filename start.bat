@echo off
cd /d "%~dp0"
git pull origin master 2>nul
python mail_reader_gui.py
