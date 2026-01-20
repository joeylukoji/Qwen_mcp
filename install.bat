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
python test_mcp.py
if errorlevel 1 (
    echo [ERREUR] Les tests ont echoue
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
