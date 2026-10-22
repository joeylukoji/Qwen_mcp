#!/usr/bin/env python3

import logging
import os
import json
import asyncio
import time
from pathlib import Path
from typing import Dict, Any, Optional
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import pandas as pd
import numpy as np

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

from mcp_server import (
    convertir_excel_en_json,
    appeler_ollama,
    OLLAMA_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
    detecter_ligne_en_tete
)

try:
    from agents import analyser_avec_agents
    AGENTS_AVAILABLE = True
except ImportError:
    AGENTS_AVAILABLE = False
    print("[WARNING] agents.py non disponible, utilisation du mode simple")

try:
    from batch_processor import traiter_fichier_par_lots_avec_analyse, BATCH_SIZE
    BATCH_PROCESSOR_AVAILABLE = True
except ImportError:
    BATCH_PROCESSOR_AVAILABLE = False
    print("[WARNING] batch_processor.py non disponible")

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['SECRET_KEY'] = os.urandom(24)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'xlsx', 'xls'}
USE_LLM = os.getenv("ENABLE_LLM", "1") not in {"0", "false", "False"}
LLM_FAILURE_COOLDOWN = int(os.getenv("LLM_COOLDOWN_SECONDS", "60"))
DERNIER_ECHEC_LLM: Optional[float] = None

def generer_resume_local(contexte_fichier: Dict[str, Any]) -> str:
    type_detecte = contexte_fichier.get("type", "inconnu")
    nombre_lignes = contexte_fichier.get("nombre_total_lignes", "inconnu")
    colonnes = contexte_fichier.get("colonnes", []) or []
    stats = contexte_fichier.get("statistiques_basiques", {}) or {}
    apercu = contexte_fichier.get("apercu_lignes", []) or []

    lignes_resume = [
        f"Type de fichier détecté : {type_detecte}",
        f"Nombre total d'enregistrements : {nombre_lignes}",
    ]

    if colonnes:
        colonnes_visibles = ", ".join(str(c) for c in colonnes[:15])
        lignes_resume.append(f"Colonnes principales ({len(colonnes)}): {colonnes_visibles}")
    else:
        lignes_resume.append("Colonnes principales : non détectées")

    if stats:
        lignes_resume.append("Statistiques basiques :")
        for idx, (col, details) in enumerate(stats.items()):
            if idx >= 5:
                lignes_resume.append("…")
                break
            stat_parts = []
            moyenne = details.get("moyenne")
            if moyenne is not None:
                stat_parts.append(f"moyenne={round(moyenne, 2)}")
            minimum = details.get("min")
            if minimum is not None:
                stat_parts.append(f"min={round(minimum, 2)}")
            maximum = details.get("max")
            if maximum is not None:
                stat_parts.append(f"max={round(maximum, 2)}")
            if stat_parts:
                lignes_resume.append(f"  - {col}: " + ", ".join(stat_parts))
    else:
        lignes_resume.append("Pas de statistiques numériques détectées.")

    if apercu:
        lignes_resume.append(f"Aperçu de {min(len(apercu), 5)} enregistrements :")
        for ligne in apercu[:5]:
            lignes_resume.append(f"  - {ligne}")

    lignes_resume.append("Résumé généré automatiquement (LLM indisponible).")
    return "\n".join(lignes_resume)

def convert_numpy_types(obj):
    if isinstance(obj, dict):
        donnees_converties = {}
        for k, v in obj.items():
            cle = k if isinstance(k, str) else str(k)
            donnees_converties[cle] = convert_numpy_types(v)
        return donnees_converties
    elif isinstance(obj, list):
        return [convert_numpy_types(i) for i in obj]
    elif isinstance(obj, (np.int_, np.intc, np.intp, np.int8,
                          np.int16, np.int32, np.int64, np.uint8,
                          np.uint16, np.uint32, np.uint64)):
        return int(obj)
    elif isinstance(obj, (np.float64, np.float16, np.float32)): 
        return float(obj)
    elif isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    elif pd.isna(obj):
        return None
    return obj

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


async def generer_resume_fichier(chemin_fichier: Path, colonnes: list, lignes: list, type_detecte: str) -> Dict[str, Any]:
    try:
        donnees_json = convertir_excel_en_json(chemin_fichier)
        if 'donnees' in donnees_json:
            premiere_feuille = list(donnees_json['donnees'].keys())[0]
            df_data = donnees_json['donnees'][premiere_feuille]
            toutes_lignes = df_data.get('lignes', [])
        else:
            toutes_lignes = donnees_json.get('lignes', [])

        CONTEXTE_MODEL_TOKENS = int(os.getenv("OLLAMA_CONTEXT_SIZE", "32000"))
        if CONTEXTE_MODEL_TOKENS >= 100000:
            TOKENS_DISPONIBLES = int(CONTEXTE_MODEL_TOKENS * 0.75)
        else:
            TOKENS_DISPONIBLES = int(CONTEXTE_MODEL_TOKENS * 0.6)

        TOKENS_PAR_LIGNE = max(50, len(colonnes) * 2)
        MAX_LIGNES_RESUME = max(30, int(TOKENS_DISPONIBLES / TOKENS_PAR_LIGNE))

        if CONTEXTE_MODEL_TOKENS >= 100000:
            MAX_LIGNES_RESUME = min(MAX_LIGNES_RESUME, 1000)
        elif CONTEXTE_MODEL_TOKENS >= 16000:
            MAX_LIGNES_RESUME = min(MAX_LIGNES_RESUME, 300)
        else:
            MAX_LIGNES_RESUME = min(MAX_LIGNES_RESUME, 150)

        lignes_resume = toutes_lignes[:MAX_LIGNES_RESUME] if len(toutes_lignes) > MAX_LIGNES_RESUME else toutes_lignes

        contexte_fichier = {
            "type": type_detecte,
            "colonnes": colonnes,
            "nombre_total_lignes": len(toutes_lignes),
            "apercu_lignes": lignes_resume,
            "statistiques_basiques": {}
        }

        try:
            df = pd.read_excel(chemin_fichier)
            from mcp_server import detecter_ligne_en_tete
            header_row = detecter_ligne_en_tete(chemin_fichier)
            df = pd.read_excel(chemin_fichier, header=header_row)

            for col in df.columns:
                try:
                    # Convertir en numérique, les erreurs deviendront NaN
                    numeric_col = pd.to_numeric(df[col], errors='coerce')
                    if not numeric_col.isna().all():
                        contexte_fichier["statistiques_basiques"][col] = {
                            "moyenne": float(numeric_col.mean()),
                            "min": float(numeric_col.min()),
                            "max": float(numeric_col.max())
                        }
                except Exception as e:
                    logging.warning(f"Impossible de calculer les statistiques pour la colonne '{col}': {e}")

        except Exception as e:
            logging.error(f"Erreur lors du calcul des statistiques dans generer_resume_fichier: {e}", exc_info=True)

        resume_auto = generer_resume_local(contexte_fichier)

        global DERNIER_ECHEC_LLM

        temps_restant = 0
        if DERNIER_ECHEC_LLM:
            delta = time.time() - DERNIER_ECHEC_LLM
            if delta < LLM_FAILURE_COOLDOWN:
                temps_restant = int(LLM_FAILURE_COOLDOWN - delta)

        resume_auto = generer_resume_local(contexte_fichier)

        if not USE_LLM:
            resume_llm = resume_auto
        elif temps_restant > 0:
            resume_llm = f"{resume_auto}\n\n[LLM désactivé temporairement ({temps_restant}s restants après un échec)]"
        elif HTTPX_AVAILABLE:
            try:
                contexte_json = json.dumps(contexte_fichier, ensure_ascii=False, indent=1)
                if len(contexte_json) > 2000:
                    contexte_reduit = {
                        "type": contexte_fichier.get("type"),
                        "colonnes": contexte_fichier.get("colonnes", [])[:20],
                        "nombre_total_lignes": contexte_fichier.get("nombre_total_lignes"),
                        "apercu_lignes": contexte_fichier.get("apercu_lignes", [])[:20],
                        "statistiques_basiques": contexte_fichier.get("statistiques_basiques", {})
                    }
                    contexte_json = json.dumps(contexte_reduit, ensure_ascii=False, indent=1)

                message_utilisateur = f"""Analyse ce fichier Excel et génère un résumé général professionnel.

Données du fichier:
{contexte_json}

Génère un résumé qui inclut:
- Le type de fichier détecté
- Le nombre total d'enregistrements
- Les colonnes principales
- Les statistiques importantes
- Les observations générales

Réponds en français de manière claire et structurée."""

                payload = {
                    "model": OLLAMA_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": """Tu es un assistant expert en analyse de données Excel.
Tu génères des résumés professionnels et structurés de fichiers Excel.
Tu analyses les données et fournis des insights pertinents."""
                        },
                        {
                            "role": "user",
                            "content": message_utilisateur
                        }
                    ],
                    "temperature": 0.3,
                    "stream": False
                }

                async def appeler_llm():
                    timeout_value = int(OLLAMA_TIMEOUT) if OLLAMA_TIMEOUT else 120
                    async with httpx.AsyncClient(timeout=timeout_value) as client:
                        response = await client.post(OLLAMA_URL, json=payload)
                        response.raise_for_status()
                        result = response.json()
                        return result.get('choices', [{}])[0].get('message', {}).get('content', 'Résumé non disponible')

                loop = asyncio.get_event_loop()
                resume_llm = await appeler_llm()
                DERNIER_ECHEC_LLM = None
            except Exception as e:
                logging.error(f"Erreur lors de l'appel LLM: {e}", exc_info=True)
                DERNIER_ECHEC_LLM = time.time()
                resume_llm = f"{resume_auto}\n\n[LLM indisponible: {str(e)}]"
        else:
            resume_llm = resume_auto

        return {
            "type": type_detecte,
            "resume": resume_llm,
            "statistiques": {
                "nombre_lignes": len(toutes_lignes),
                "nombre_colonnes": len(colonnes),
                "colonnes": colonnes,
                "statistiques_basiques": contexte_fichier.get("statistiques_basiques", {})
            },
            "donnees_completes": donnees_json
        }
    except Exception as e:
        logging.error(f"Erreur majeure dans generer_resume_fichier: {e}", exc_info=True)
        return {"erreur": str(e), "type": "erreur"}


async def analyser_fichier_excel(chemin_fichier: Path, type_analyse: str = "auto") -> Dict[str, Any]:
    try:
        donnees_json = convertir_excel_en_json(chemin_fichier)
        if 'donnees' in donnees_json:
            premiere_feuille = list(donnees_json['donnees'].keys())[0]
            df_data = donnees_json['donnees'][premiere_feuille]
        else:
            df_data = donnees_json

        colonnes = df_data.get('colonnes', [])
        lignes = df_data.get('lignes', [])

        if type_analyse == "auto":
            type_detecte = detecter_type_fichier(colonnes, lignes)
        else:
            type_detecte = type_analyse

        return await generer_resume_fichier(chemin_fichier, colonnes, lignes, type_detecte)

    except Exception as e:
        logging.error(f"Erreur dans analyser_fichier_excel: {e}", exc_info=True)
        return {
            "erreur": str(e),
            "type": "erreur"
        }


def detecter_type_fichier(colonnes: list, lignes: list) -> str:
    colonnes_lower = [col.lower() for col in colonnes]

    if any(mot in ' '.join(colonnes_lower) for mot in ['nom', 'classe', 'note', 'moyenne', 'absence']):
        return "students"
    if any(mot in ' '.join(colonnes_lower) for mot in ['produit', 'prix', 'stock', 'client', 'vente', 'revenu']):
        return "entreprise"
    if any(mot in ' '.join(colonnes_lower) for mot in ['rang', 'classement', 'score', 'performance', 'resultat']):
        return "palmares"

    return "generique"


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"erreur": "Aucun fichier fourni"}), 400

    file = request.files['file']
    type_analyse = request.form.get('type_analyse', 'auto')

    if file.filename == '':
        return jsonify({"erreur": "Aucun fichier sélectionné"}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = Path(app.config['UPLOAD_FOLDER']) / filename
        file.save(str(filepath))

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            resultat = loop.run_until_complete(analyser_fichier_excel(filepath, type_analyse))
            loop.close()
            
            # Nettoyer le resultat avant de le passer à jsonify
            resultat_nettoye = convert_numpy_types(resultat)
            
            resultat_nettoye['fichier_path'] = str(filepath)

            return jsonify(resultat_nettoye)
        except Exception as e:
            logging.error(f"Erreur dans upload_file: {e}", exc_info=True)
            return jsonify({"erreur": str(e), "type": "erreur"}), 500

    return jsonify({"erreur": "Type de fichier non autorisé"}), 400


@app.route('/api/chatbot', methods=['POST'])
def chatbot():
    try:
        data = request.json
        message = data.get('message', '')
        fichier_path = data.get('fichier_path')
        if not message:
            return jsonify({"erreur": "Message vide"}), 400
        utiliser_batch = data.get('mode_batch', False)
        if BATCH_PROCESSOR_AVAILABLE and fichier_path and (utiliser_batch or len(message) > 100):
            fichier = Path(fichier_path)
            if not fichier.is_absolute():
                fichier = Path(app.config['UPLOAD_FOLDER']) / fichier.name

            if fichier.exists():
                print(f"[CHATBOT] Utilisation du traitement par lots ({BATCH_SIZE} lignes/bloc) pour: {fichier.name}")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    reponse = loop.run_until_complete(traiter_fichier_par_lots_avec_analyse(fichier, message))
                    return jsonify({
                        "reponse": reponse,
                        "fichier_inclus": True,
                        "mode": "batch-processor",
                        "batch_size": BATCH_SIZE
                    })
                except Exception as e:
                    import traceback
                    error_details = traceback.format_exc()
                    print(f"[ERREUR BATCH PROCESSOR] {error_details}")
                    print(f"[CHATBOT] Erreur batch processor, passage au mode multi-agents")
                finally:
                    loop.close()

        if AGENTS_AVAILABLE and fichier_path:
            fichier = Path(fichier_path)
            if not fichier.is_absolute():
                fichier = Path(app.config['UPLOAD_FOLDER']) / fichier.name

            if fichier.exists():
                print(f"[CHATBOT] Utilisation du système multi-agents pour: {fichier.name}")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    reponse = loop.run_until_complete(analyser_avec_agents(fichier, message))
                    return jsonify({
                        "reponse": reponse,
                        "fichier_inclus": True,
                        "mode": "multi-agents"
                    })
                except Exception as e:
                    import traceback
                    error_details = traceback.format_exc()
                    print(f"[ERREUR MULTI-AGENTS] {error_details}")
                    print(f"[CHATBOT] Erreur multi-agents, passage au mode simple")
                finally:
                    loop.close()

        print(f"[CHATBOT] Utilisation du mode simple (fallback)")
        contexte_fichier = ""
        if fichier_path:
            fichier = Path(fichier_path)
            if not fichier.is_absolute():
                fichier = Path(app.config['UPLOAD_FOLDER']) / fichier.name

            if fichier.exists():
                try:
                    donnees_json = convertir_excel_en_json(fichier)
                    if 'donnees' in donnees_json:
                        premiere_feuille = list(donnees_json['donnees'].keys())[0]
                        df_data = donnees_json['donnees'][premiere_feuille]
                        colonnes = df_data.get('colonnes', [])
                        lignes = df_data.get('lignes', [])
                    else:
                        colonnes = donnees_json.get('colonnes', [])
                        lignes = donnees_json.get('lignes', [])

                    def nettoyer_nan(obj):
                        if isinstance(obj, dict):
                            return {k: nettoyer_nan(v) for k, v in obj.items()}
                        elif isinstance(obj, list):
                            return [nettoyer_nan(item) for item in obj]
                        elif pd.isna(obj) if hasattr(pd, 'isna') else (obj != obj if isinstance(obj, float) else False):
                            return None
                        elif isinstance(obj, float) and (obj != obj):
                            return None
                        return obj

                    lignes_nettoyees = nettoyer_nan(lignes)
                    CONTEXTE_MODEL_TOKENS = int(os.getenv("LM_STUDIO_CONTEXT_SIZE", "168000"))
                    print(f"[DEBUG] Contexte détecté: {CONTEXTE_MODEL_TOKENS} tokens")
                    if CONTEXTE_MODEL_TOKENS >= 100000:
                        TOKENS_DISPONIBLES = int(CONTEXTE_MODEL_TOKENS * 0.80)
                    else:
                        TOKENS_DISPONIBLES = int(CONTEXTE_MODEL_TOKENS * 0.70)
                    MAX_LLM_CHARS = int(TOKENS_DISPONIBLES * 4)
                    TOKENS_PAR_LIGNE = max(30, len(colonnes) * 1.5)
                    MAX_LLM_LINES = max(20, int(TOKENS_DISPONIBLES / TOKENS_PAR_LIGNE))
                    if CONTEXTE_MODEL_TOKENS >= 100000:
                        MAX_LLM_LINES = max(MAX_LLM_LINES, 1000)
                        MAX_LLM_LINES = min(MAX_LLM_LINES, 5000)
                        MAX_LLM_CHARS = min(MAX_LLM_CHARS, 500000)
                    elif CONTEXTE_MODEL_TOKENS >= 16000:
                        MAX_LLM_LINES = min(MAX_LLM_LINES, 500)
                        MAX_LLM_CHARS = min(MAX_LLM_CHARS, 50000)
                    else:
                        MAX_LLM_LINES = min(MAX_LLM_LINES, 200)
                        MAX_LLM_CHARS = min(MAX_LLM_CHARS, 10000)
                    print(f"[DEBUG] Limites calculées: {MAX_LLM_LINES} lignes max, {MAX_LLM_CHARS} caractères max")
                    print(f"[DEBUG] Fichier a {len(lignes_nettoyees)} lignes totales")
                    stats_completes = {}
                    try:
                        df_complet = pd.read_excel(fichier)
                        from mcp_server import detecter_ligne_en_tete
                        header_row = detecter_ligne_en_tete(fichier)
                        df_complet = pd.read_excel(fichier, header=header_row)

                        for col in df_complet.select_dtypes(include=['number']).columns:
                            if not df_complet[col].isna().all():
                                stats_completes[col] = {
                                    "moyenne": float(df_complet[col].mean()),
                                    "min": float(df_complet[col].min()),
                                    "max": float(df_complet[col].max()),
                                    "total": int(df_complet[col].notna().sum())
                                }
                    except:
                        pass

                    if CONTEXTE_MODEL_TOKENS >= 100000:
                        if len(lignes_nettoyees) <= MAX_LLM_LINES:
                            lignes_pour_llm = lignes_nettoyees
                            print(f"[DEBUG] Envoi de TOUTES les {len(lignes_pour_llm)} lignes (contexte 168k+)")
                        else:
                            lignes_pour_llm = lignes_nettoyees[:MAX_LLM_LINES]
                            print(f"[DEBUG] Envoi de {len(lignes_pour_llm)} lignes sur {len(lignes_nettoyees)} (limite: {MAX_LLM_LINES})")
                    elif len(lignes_nettoyees) > MAX_LLM_LINES:
                        echantillon = []
                        echantillon.extend(lignes_nettoyees[:MAX_LLM_LINES//2])
                        milieu = len(lignes_nettoyees) // 2
                        echantillon.extend(lignes_nettoyees[milieu:milieu + MAX_LLM_LINES//4])
                        lignes_pour_llm = echantillon[:MAX_LLM_LINES]
                        print(f"[DEBUG] Échantillon de {len(lignes_pour_llm)} lignes")
                    else:
                        lignes_pour_llm = lignes_nettoyees
                        print(f"[DEBUG] Envoi de toutes les {len(lignes_pour_llm)} lignes")

                    try:
                        lignes_json = json.dumps(lignes_pour_llm, ensure_ascii=False, indent=1, default=str)
                        print(f"[DEBUG] Taille JSON: {len(lignes_json)} caractères (limite: {MAX_LLM_CHARS})")
                        if len(lignes_json) > MAX_LLM_CHARS:
                            lignes_json = lignes_json[:MAX_LLM_CHARS] + "... (aperçu tronqué)"
                            print(f"[DEBUG] JSON tronqué à {MAX_LLM_CHARS} caractères")
                    except Exception as e:
                        print(f"[DEBUG] Erreur lors de la conversion JSON: {e}")
                        lignes_json = json.dumps(lignes_pour_llm[:min(100, len(lignes_pour_llm))], ensure_ascii=False, indent=1, default=str)

                    colonnes_affichage = colonnes[:15] if len(colonnes) > 15 else colonnes
                    stats_json = json.dumps(stats_completes, ensure_ascii=False, indent=1) if stats_completes else "Aucune colonne numérique"
                    if len(lignes_pour_llm) == len(lignes_nettoyees):
                        message_lignes = f"TOUTES les {len(lignes_pour_llm)} lignes du fichier sont incluses ci-dessous."
                    else:
                        message_lignes = f"Échantillon de {len(lignes_pour_llm)} lignes sur {len(lignes_nettoyees)} totales (contexte: {CONTEXTE_MODEL_TOKENS} tokens)."

                    contexte_fichier = f"""
Fichier Excel analysé (FICHIER LU ENTIÈREMENT):
- Nombre total de lignes: {len(lignes_nettoyees)}
- Nombre de colonnes: {len(colonnes)}
- Colonnes: {', '.join(colonnes_affichage)}{'...' if len(colonnes) > 15 else ''}
- Contexte disponible: {CONTEXTE_MODEL_TOKENS} tokens

STATISTIQUES COMPLÈTES (calculées sur TOUTES les {len(lignes_nettoyees)} lignes):
{stats_json}

DONNÉES ({message_lignes}):
{lignes_json}

IMPORTANT: Le fichier complet a été lu et analysé. Les statistiques ci-dessus sont calculées sur TOUTES les données.
"""
                except Exception as e:
                    contexte_fichier = f"Erreur lors de l'analyse du fichier: {str(e)}"

        message_complet = f"""{contexte_fichier}

Instructions de l'utilisateur:
{message}

Réponds de manière claire et professionnelle en te basant sur TOUTES les données du fichier Excel fourni."""

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            if HTTPX_AVAILABLE:
                import httpx
                api_url = OLLAMA_URL

                payload = {
                    "model": OLLAMA_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": """Tu es un assistant intelligent qui aide à analyser des fichiers Excel.
Tu reçois des données Excel complètes et des instructions de l'utilisateur.
Réponds de manière claire, professionnelle et utile.
Utilise TOUTES les données fournies pour répondre aux questions de manière précise.
Si des statistiques sont demandées, calcule-les à partir des données fournies.
Si des questions spécifiques sont posées, cherche dans toutes les données pour trouver la réponse."""
                        },
                        {
                            "role": "user",
                            "content": message_complet
                        }
                    ],
                    "temperature": 0.7,
                    "stream": False
                }
                async def appeler_llm():
                    timeout_value = int(OLLAMA_TIMEOUT) if OLLAMA_TIMEOUT else 120
                    async with httpx.AsyncClient(timeout=timeout_value) as client:
                        response = await client.post(api_url, json=payload)
                        if response.status_code != 200:
                            error_text = response.text
                            try:
                                error_json = response.json()
                                error_text = json.dumps(error_json, indent=2, ensure_ascii=False)
                            except:
                                pass
                            raise httpx.HTTPStatusError(
                                f"Erreur {response.status_code}: {error_text}",
                                request=response.request,
                                response=response
                            )
                        response.raise_for_status()
                        result = response.json()
                        return result.get('choices', [{}])[0].get('message', {}).get('content', 'Erreur: réponse vide')

                reponse = loop.run_until_complete(appeler_llm())
            else:
                reponse = "Erreur: httpx n'est pas disponible. Le LLM ne peut pas être contacté."
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"[ERREUR] Erreur lors de l'appel au LLM:")
            print(error_details)
            reponse = f"Erreur lors de l'appel au LLM: {str(e)}\n\nDétails: {error_details}"
        finally:
            loop.close()

        return jsonify({
            "reponse": reponse,
            "fichier_inclus": fichier_path is not None,
            "mode": "simple"
        })

    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "ok",
        "ollama_available": HTTPX_AVAILABLE,
        "ollama_url": OLLAMA_URL,
        "ollama_model": OLLAMA_MODEL
    })


if __name__ == '__main__':
    # Debug mode and network exposure are opt-in: the Werkzeug debugger allows remote code execution.
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1",
            host=os.getenv("HOST", "127.0.0.1"),
            port=int(os.getenv("PORT", "5000")))
