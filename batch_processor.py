#!/usr/bin/env python3

import json
import os
import asyncio
from typing import Dict, Any, List, Optional
from pathlib import Path
import pandas as pd
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

from mcp_server import detecter_ligne_en_tete

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/v1/chat/completions")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "20"))


def nettoyer_nan_recursif(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: nettoyer_nan_recursif(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [nettoyer_nan_recursif(item) for item in obj]
    elif pd.isna(obj) if hasattr(pd, 'isna') else (obj != obj if isinstance(obj, float) else False):
        return None
    elif isinstance(obj, float) and (obj != obj):
        return None
    return obj


def preparer_bloc_csv(df_bloc: pd.DataFrame) -> str:
    return df_bloc.to_csv(index=False, lineterminator='\n')


async def traiter_bloc_llm(bloc_csv: str, colonnes: List[str], prompt_system: Optional[str] = None) -> Dict[str, Any]:
    if not HTTPX_AVAILABLE:
        raise ImportError("httpx n'est pas installé. Installez-le avec: pip install httpx")

    system_prompt = prompt_system or """Tu es un expert en extraction de données Excel.
Tu reçois un tableau CSV de 20 lignes et tu génères un tableau JSON valide.
Chaque objet JSON doit contenir toutes les colonnes du tableau.
Réponds UNIQUEMENT par le code JSON, sans introduction ni conclusion.
Le JSON doit être un tableau d'objets valide."""

    user_prompt = f"""Convertis ces {BATCH_SIZE} lignes Excel en JSON.
Chaque objet doit contenir toutes les colonnes suivantes : {', '.join(colonnes)}.
Réponds uniquement par le code JSON, sans introduction ni conclusion.

Données CSV :
{bloc_csv}"""

    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            payload = {
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.1,
                "stream": False
            }

            response = await client.post(OLLAMA_URL, json=payload)
            response.raise_for_status()
            result = response.json()

            reponse_text = result.get('choices', [{}])[0].get('message', {}).get('content', '[]')

            try:
                if '[' in reponse_text:
                    json_start = reponse_text.find('[')
                    json_end = reponse_text.rfind(']') + 1
                    json_str = reponse_text[json_start:json_end]
                    donnees_json = json.loads(json_str)
                else:
                    donnees_json = json.loads(reponse_text)

                if not isinstance(donnees_json, list):
                    donnees_json = [donnees_json]

                return {"succes": True, "donnees": donnees_json, "erreur": None}

            except json.JSONDecodeError as e:
                return {
                    "succes": False,
                    "donnees": [],
                    "erreur": f"Erreur de parsing JSON: {str(e)}. Réponse LLM: {reponse_text[:200]}"
                }

    except httpx.HTTPStatusError as e:
        return {
            "succes": False,
            "donnees": [],
            "erreur": f"Erreur HTTP {e.response.status_code}: {e.response.text[:200]}"
        }
    except Exception as e:
        return {
            "succes": False,
            "donnees": [],
            "erreur": f"Erreur lors de l'appel au LLM: {str(e)}"
        }


async def traiter_fichier_par_lots(chemin_fichier: Path, callback_progression: Optional[callable] = None) -> Dict[str, Any]:
    try:
        header_row = detecter_ligne_en_tete(chemin_fichier)
        df_complet = pd.read_excel(chemin_fichier, header=header_row)
        df_complet.columns = [str(col).strip() if pd.notna(col) else f"Colonne_{i}"
                             for i, col in enumerate(df_complet.columns)]

        total_lignes = len(df_complet)
        colonnes = df_complet.columns.tolist()

        print(f"[BATCH PROCESSOR] Fichier chargé: {total_lignes} lignes, {len(colonnes)} colonnes")
        print(f"[BATCH PROCESSOR] Traitement par lots de {BATCH_SIZE} lignes")

        # Calculer le nombre de lots
        nombre_lots = (total_lignes + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"[BATCH PROCESSOR] {nombre_lots} lots à traiter")
        toutes_donnees = []
        erreurs = []
        statistiques = {
            "total_lignes": total_lignes,
            "total_colonnes": len(colonnes),
            "nombre_lots": nombre_lots,
            "lots_reussis": 0,
            "lots_echoues": 0,
            "lignes_traitees": 0
        }

        for lot_num in range(nombre_lots):
            debut = lot_num * BATCH_SIZE
            fin = min(debut + BATCH_SIZE, total_lignes)

            df_bloc = df_complet.iloc[debut:fin].copy()
            print(f"[BATCH PROCESSOR] Lot {lot_num + 1}/{nombre_lots}: lignes {debut + 1}-{fin}")
            bloc_csv = preparer_bloc_csv(df_bloc)
            resultat = await traiter_bloc_llm(bloc_csv, colonnes)

            if resultat["succes"]:
                donnees_bloc = resultat["donnees"]
                toutes_donnees.extend(donnees_bloc)
                statistiques["lots_reussis"] += 1
                statistiques["lignes_traitees"] += len(donnees_bloc)
                print(f"[BATCH PROCESSOR] ✓ Lot {lot_num + 1} traité: {len(donnees_bloc)} objets")
            else:
                erreurs.append({
                    "lot": lot_num + 1,
                    "lignes": f"{debut + 1}-{fin}",
                    "erreur": resultat["erreur"]
                })
                statistiques["lots_echoues"] += 1
                print(f"[BATCH PROCESSOR] ✗ Lot {lot_num + 1} échoué: {resultat['erreur']}")

            if callback_progression:
                callback_progression(fin, total_lignes, lot_num + 1)
            await asyncio.sleep(0.1)
        toutes_donnees = nettoyer_nan_recursif(toutes_donnees)

        print(f"[BATCH PROCESSOR] Traitement terminé: {statistiques['lignes_traitees']}/{total_lignes} lignes traitées")
        print(f"[BATCH PROCESSOR] {statistiques['lots_reussis']} lots réussis, {statistiques['lots_echoues']} lots échoués")

        return {
            "succes": True,
            "donnees_totales": toutes_donnees,
            "statistiques": statistiques,
            "erreurs": erreurs,
            "colonnes": colonnes
        }

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"[BATCH PROCESSOR] Erreur: {error_details}")
        return {
            "succes": False,
            "donnees_totales": [],
            "statistiques": {},
            "erreurs": [{"erreur": str(e), "details": error_details}],
            "colonnes": []
        }


async def traiter_fichier_par_lots_avec_analyse(chemin_fichier: Path, question: Optional[str] = None) -> str:
    resultat = await traiter_fichier_par_lots(chemin_fichier)

    if not resultat["succes"]:
        return f"Erreur lors du traitement: {resultat['erreurs']}"

    stats = resultat["statistiques"]
    donnees = resultat["donnees_totales"]
    echantillon_size = min(50, len(donnees))
    if len(donnees) <= echantillon_size:
        echantillon = donnees
    else:
        debut = donnees[:echantillon_size // 3]
        milieu = donnees[len(donnees) // 2:len(donnees) // 2 + echantillon_size // 3]
        fin = donnees[-echantillon_size // 3:]
        echantillon = debut + milieu + fin

    if not HTTPX_AVAILABLE:
        return f"Fichier traité: {stats['lignes_traitees']} lignes sur {stats['total_lignes']} totales."

    prompt_analyse = f"""Tu as accès à un fichier Excel complet qui a été traité.

STATISTIQUES COMPLÈTES:
- Total de lignes: {stats['total_lignes']}
- Lignes traitées avec succès: {stats['lignes_traitees']}
- Nombre de colonnes: {stats['total_colonnes']}
- Colonnes: {', '.join(resultat['colonnes'][:20])}
- Lots réussis: {stats['lots_reussis']}/{stats['nombre_lots']}

ÉCHANTILLON REPRÉSENTATIF (début, milieu, fin du fichier):
{json.dumps(echantillon, ensure_ascii=False, indent=2)[:5000]}

QUESTION DE L'UTILISATEUR:
{question or 'Fais un résumé général du fichier'}

TÂCHE: Analyse le fichier complet en utilisant les statistiques globales ET l'échantillon représentatif.
Donne une réponse complète et précise basée sur TOUTES les données traitées."""

    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            payload = {
                "model": OLLAMA_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": "Tu es un expert en analyse de données Excel. Tu analyses des fichiers complets avec des statistiques globales et des échantillons représentatifs."
                    },
                    {
                        "role": "user",
                        "content": prompt_analyse
                    }
                ],
                "temperature": 0.7,
                "stream": False
            }

            response = await client.post(OLLAMA_URL, json=payload)
            response.raise_for_status()
            result = response.json()
            return result.get('choices', [{}])[0].get('message', {}).get('content', 'Erreur: réponse vide')

    except Exception as e:
        return f"Erreur lors de l'analyse: {str(e)}"


async def inserer_en_base_par_lots(donnees: List[Dict[str, Any]],
                                   table_name: str,
                                   connection_string: Optional[str] = None) -> Dict[str, Any]:
    return {
        "succes": False,
        "message": "Fonction d'insertion en base non implémentée. À adapter selon votre BDD."
    }
