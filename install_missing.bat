@echo off
cd c:\Users\HP\OneDrive\Documents\Desktop\SELF-HEALING
call venv\Scripts\activate.bat
pip install python-dotenv pydantic
python backend/config.py
pause
