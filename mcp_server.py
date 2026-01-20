#!/usr/bin/env python3
"""
Serveur MCP pour la conversion de fichiers Excel en JSON.
Système générique avec détection automatique de la ligne d'en-tête.
"""

import logging
import json
import sys
import os
from typing import Any, Dict, List, Optional
from pathlib import Path
import pandas as pd

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    class Server:
        def __init__(self, name):
            self.name = name
    class Tool:
        pass
    class TextContent:
        pass

if MCP_AVAILABLE:
    app = Server("excel-analyzer")
else:
    app = None

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/v1/chat/completions")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

MASTER_PROMPT = """### RÔLE
Tu es un Système Multi-Agent d'Encodage Administratif. Ton objectif est de transformer des données brutes (extraites d'Excel) en documents JSON structurés et en analyses décisionnelles pour une administration scolaire.

### MISSIONS
1. **TRANSCRIPTION :** Convertir les données textuelles en format JSON strict.
2. **CALCUL :** CALCULER la moyenne des notes (somme des notes divisée par le nombre de notes valides). Exclure les valeurs null.
3. **ANALYSE :** Évaluer les performances selon les critères suivants :
   - Moyenne 
   - Si Absences 
4. **RÉDACTION :** Générer une observation formelle pour le bulletin.

### FORMAT DE SORTIE OBLIGATOIRE (JSON)
Tu dois impérativement répondre sous ce format JSON, sans texte superflu :
{
  "student": { "nom": "", "classe": "" },
  "notes": { "matiere": note },
  "analyse": {
    "moyenne": float,
    "statut": "Admis" | "Échec",
    "observation": "Texte formel"
  }
}

### RÈGLES CRITIQUES
- CALCULER la moyenne : additionner toutes les notes numériques (ignorer null), puis diviser par le nombre de notes valides.
- Ne jamais inventer de données.
- Si une note est illisible, mets "null" dans les notes, mais ne l'inclus PAS dans le calcul de la moyenne.
- Le statut "Admis" si moyenne >= 10, "Échec" si moyenne < 10.
- Utilise un ton administratif froid et professionnel."""


def detecter_ligne_en_tete(chemin_fichier: Path, feuille: Optional[str] = None, max_lignes: int = 5) -> int:
    """
    Détecte automatiquement la ligne contenant les en-têtes.
    Cherche la ligne avec le plus de valeurs non-null et des noms de colonnes cohérents.
    """
    try:
        df_test = pd.read_excel(chemin_fichier, sheet_name=feuille if feuille else 0,
                                nrows=max_lignes, header=None)

        scores = []
        for idx in range(min(max_lignes, len(df_test))):
            row = df_test.iloc[idx]
            non_null_count = int(row.notna().sum())
            
            text_count = int(sum(1 for val in row if pd.notna(val) and isinstance(str(val), str) and len(str(val).strip()) > 0))
            score = non_null_count * 2 + text_count
            scores.append((idx, score))
        if scores:
            best_row = max(scores, key=lambda x: x[1])[0]
            return best_row
        return 0
    except Exception as e:
        logging.error(f"Erreur dans detecter_ligne_en_tete: {e}", exc_info=True)
        return 0


def nettoyer_nan_recursif(obj):
    """
    Nettoie récursivement tous les NaN d'une structure de données.
    Convertit les NaN en None pour la sérialisation JSON.
    """
    if isinstance(obj, dict):
        return {k: nettoyer_nan_recursif(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [nettoyer_nan_recursif(item) for item in obj]
    elif pd.isna(obj) if hasattr(pd, 'isna') else (isinstance(obj, float) and obj != obj):
        return None
    elif isinstance(obj, float):
        if obj != obj:
            return None
    return obj



def convertir_excel_en_json(chemin_fichier: Path, feuille: Optional[str] = None,
                            inclure_index: bool = False, header_row: Optional[int] = None) -> Dict[str, Any]:
    """
    Convertit n'importe quel fichier Excel en JSON de manière générique.
    Gère automatiquement tous les types de données et toutes les structures.

    Args:
        header_row: Numéro de ligne (0-indexed) contenant les en-têtes.
                   Si None, détecte automatiquement.
    """
    try:
        if header_row is None:
            header_row = detecter_ligne_en_tete(chemin_fichier, feuille)
        if feuille:
            df = pd.read_excel(chemin_fichier, sheet_name=feuille, header=header_row)
            df.columns = [str(col).strip() if pd.notna(col) else f"Colonne_{i}" for i, col in enumerate(df.columns)]
            lignes_dict = df.to_dict(orient="records", into=dict)
            lignes_nettoyees = nettoyer_nan_recursif(lignes_dict)

            resultat = {
                "feuille": feuille,
                "ligne_en_tete": header_row,
                "colonnes": df.columns.tolist(),
                "nombre_lignes": len(df),
                "lignes": lignes_nettoyees if isinstance(lignes_nettoyees, list) else [lignes_nettoyees]
            }
        else:
            excel_file = pd.ExcelFile(chemin_fichier)
            resultat = {
                "feuilles": excel_file.sheet_names,
                "donnees": {}
            }

            for sheet_name in excel_file.sheet_names:
                sheet_header_row = detecter_ligne_en_tete(chemin_fichier, sheet_name)
                df = pd.read_excel(excel_file, sheet_name=sheet_name, header=sheet_header_row)
                df.columns = [str(col).strip() if pd.notna(col) else f"Colonne_{i}" for i, col in enumerate(df.columns)]
                lignes_dict = df.to_dict(orient="records", into=dict)
                lignes_nettoyees = nettoyer_nan_recursif(lignes_dict)

                resultat["donnees"][sheet_name] = {
                    "ligne_en_tete": sheet_header_row,
                    "colonnes": df.columns.tolist(),
                    "nombre_lignes": len(df),
                    "lignes": lignes_nettoyees if isinstance(lignes_nettoyees, list) else [lignes_nettoyees]
                }

        return resultat

    except Exception as e:
        logging.error(f"Erreur dans convertir_excel_en_json: {e}", exc_info=True)
        raise ValueError(f"Erreur lors de la lecture du fichier Excel: {str(e)}")
   

async def appeler_ollama(donnees_brutes: Dict[str, Any], url: Optional[str] = None, custom_prompt: Optional[str] = None) -> Dict[str, Any]:
    """Envoie les données brutes au LLM via Ollama et récupère l'analyse."""
    if not HTTPX_AVAILABLE:
        raise ImportError("httpx n'est pas installé. Installez-le avec: pip install httpx")
    api_url = url or OLLAMA_URL
    message_utilisateur = f"""Analyse les données suivantes extraites d'un fichier Excel et génère le JSON structuré selon le format requis :

{json.dumps(donnees_brutes, ensure_ascii=False, indent=2)}
"""
    system_prompt = custom_prompt if custom_prompt else MASTER_PROMPT

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message_utilisateur}
        ],
        "temperature": 0.1,  
        "stream": False  
    }

    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            response = await client.post(api_url, json=payload)
            response.raise_for_status()

            result = response.json()
            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0]["message"]["content"]
                try:
                    content_clean = content.strip()
                    if content_clean.startswith("```json"):
                        lines = content_clean.split("\n")
                        content_clean = "\n".join(lines[1:-1]) if len(lines) > 2 else content_clean

                    return json.loads(content_clean)
                except json.JSONDecodeError:
                    raise ValueError(f"Le LLM n'a pas retourné un JSON valide. Réponse: {content}")
            else:
                raise ValueError("Réponse invalide de Ollama")

    except httpx.RequestError as e:
        raise ConnectionError(f"Impossible de se connecter à Ollama à {api_url}. Assurez-vous que Ollama est démarré et que l'API est activée. Erreur: {str(e)}")
    except httpx.HTTPStatusError as e:
        error_details = e.response.text
        raise ConnectionError(f"Erreur HTTP {e.response.status_code} de Ollama: {error_details}\n\nVérifiez que:\n1. Ollama est démarré\n2. Le modèle '{OLLAMA_MODEL}' est chargé\n3. L'API est activée dans Ollama")


if MCP_AVAILABLE and app:
    @app.list_tools()
    async def list_tools() -> List[Tool]:
        """Liste les outils disponibles."""
        return [
            Tool(
                name="excel_vers_json",
                description="Convertit n'importe quel fichier Excel en JSON de manière générique avec détection automatique de la ligne d'en-tête. Lit toutes les feuilles et convertit toutes les données sans présupposer de structure.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "chemin_fichier": {
                            "type": "string",
                            "description": "Chemin absolu ou relatif vers le fichier Excel (.xlsx ou .xls)"
                        },
                        "feuille": {
                            "type": "string",
                            "description": "Nom de la feuille à lire (optionnel, si non spécifié lit toutes les feuilles)",
                            "default": None
                        }
                    },
                    "required": ["chemin_fichier"]
                }
            )
        ]


if MCP_AVAILABLE and app:
    @app.call_tool()
    async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        """Exécute les outils disponibles."""

        if name == "excel_vers_json":
            chemin = Path(arguments["chemin_fichier"])
            if not chemin.exists():
                return [TextContent(
                    type="text",
                    text=json.dumps({"erreur": f"Le fichier {chemin} n'existe pas."}, ensure_ascii=False, indent=2)
                )]

            try:
                feuille = arguments.get("feuille")
                resultat = convertir_excel_en_json(chemin, feuille)

                return [TextContent(
                    type="text",
                    text=json.dumps(resultat, ensure_ascii=False, indent=2, default=str)
                )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({"erreur": f"Erreur lors de la conversion: {str(e)}"}, ensure_ascii=False, indent=2)
                )]

        else:
            return [TextContent(
                type="text",
                text=json.dumps({"erreur": f"Outil '{name}' non reconnu."}, ensure_ascii=False, indent=2)
            )]


async def main():
    """Point d'entrée principal du serveur MCP."""
    if not MCP_AVAILABLE:
        print("Erreur: Le module MCP n'est pas installé. Installez-le avec: pip install mcp")
        sys.exit(1)
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    if MCP_AVAILABLE:
        import asyncio
        asyncio.run(main())
    else:
        print("Erreur: Le module MCP n'est pas installé.")
        print("Installez les dépendances avec: pip install -r requirements.txt")
        sys.exit(1)
