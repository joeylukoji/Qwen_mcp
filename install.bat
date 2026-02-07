@echo off
echo Installation du systeme MCP d'analyse Excel...
echo.

echo [INFO] Ollama est requis pour l'inférence locale avec Qwen2.5:3b.
echo [INFO] Installez Ollama en suivant la documentation officielle : https://ollama.com/download
echo [INFO] Pour installer le package Python d'intégration Ollama :
pip install ollama
echo.

REM Vérifier si Python est installé
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou n'est pas dans le PATH
    pause
    exit /b 1
)

echo [1/2] Installation des dependances Python...
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERREUR] Echec de l'installation des dependances
    pause
    exit /b 1
)

echo.
echo [2/2] Verification de l'installation...
python -c "from mcp_server import convertir_excel_en_json; from web_server import app; print('[OK] Modules charges.')"
if errorlevel 1 (
    echo [ERREUR] Les modules n'ont pas pu etre charges. Verifiez les dependances.
    pause
    exit /b 1
)

echo.
echo [SUCCES] Installation terminee avec succes!
echo.
echo Pour utiliser le serveur MCP, configurez-le dans votre editeur (Cursor/VSCode)
echo en ajoutant la configuration dans mcp.json
echo.
pause
