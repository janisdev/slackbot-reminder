@echo off
setlocal

if not exist ".venv" (
  py -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt

if not exist "config.json" (
  echo [ERROR] config.json nav atrasts.
  echo Nokope config.example.json uz config.json un ieliec tokenu.
  exit /b 1
)

python slack_remind.py --dry-run
echo.
echo Ja viss izskatas pareizi, palaid bez --dry-run:
echo   python slack_remind.py

endlocal
