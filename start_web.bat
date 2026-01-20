@echo off
echo Demarrage du serveur web d'analyse Excel...
echo.

REM Verifier si Python est installe
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou n'est pas dans le PATH
    pause
    exit /b 1
)

REM Installer les dependances si necessaire
echo [1/2] Verification des dependances...
pip install flask werkzeug >nul 2>&1

echo.
echo [2/2] Demarrage du serveur web...
echo.
echo Le serveur sera accessible sur: http://localhost:5000
echo Appuyez sur Ctrl+C pour arreter le serveur
echo.

python web_server.py

pause
