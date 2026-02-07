#!/usr/bin/env python3

import logging
import os
import json
from pathlib import Path
from typing import Dict, Any, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
import pandas as pd
import numpy as np

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from mcp_server import convertir_excel_en_json, detecter_ligne_en_tete
import database as db

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['SECRET_KEY'] = os.urandom(24)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'csv', 'pdf'}

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def charger_donnees_fichier(fichier_path: str) -> Dict[str, Any] | None:
    """Charge les données d'un fichier Excel ou CSV pour le chatbot (format unifié)."""
    path = Path(fichier_path)
    if not path.exists():
        return None
    try:
        suffix = path.suffix.lower()
        if suffix in ('.xlsx', '.xls'):
            resultat = convertir_excel_en_json(path)
            # Normaliser la structure Excel (une ou plusieurs feuilles) vers columns/data/nb_lignes_total
            if "feuille" in resultat:
                colonnes = resultat.get("colonnes", [])
                lignes = resultat.get("lignes", [])
                return {
                    "filename": path.name,
                    "columns": colonnes,
                    "data": convert_numpy_types(lignes[:300]) if lignes else [],
                    "nb_lignes_total": resultat.get("nombre_lignes", 0),
                }
            if "donnees" in resultat and resultat["donnees"]:
                premiere_feuille = next(iter(resultat["donnees"].values()))
                colonnes = premiere_feuille.get("colonnes", [])
                lignes = premiere_feuille.get("lignes", [])
                nb_total = sum(s.get("nombre_lignes", 0) for s in resultat["donnees"].values())
                return {
                    "filename": path.name,
                    "columns": colonnes,
                    "data": convert_numpy_types(lignes[:300]) if lignes else [],
                    "nb_lignes_total": nb_total,
                    "feuilles": resultat.get("feuilles", []),
                }
            return None
        if suffix == '.csv':
            df = pd.read_csv(path)
            return {
                "filename": path.name,
                "columns": df.columns.tolist(),
                "data": convert_numpy_types(df.head(300).to_dict(orient='records')),
                "nb_lignes_total": len(df),
            }
        return None
    except Exception as e:
        logging.error(f"Erreur chargement fichier pour chatbot: {e}", exc_info=True)
        return None


# Configuration LLM (Ollama) pour questions ouvertes
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "120"))


# Nombre max de lignes envoyées au LLM (32k tokens permet ~500 lignes selon la largeur)
LLM_MAX_LIGNES = int(os.environ.get("LLM_MAX_LIGNES", "500"))
# Taille de contexte demandée à Ollama (tokens) — qwen2.5:3b supporte jusqu'à 32768
LLM_NUM_CTX = int(os.environ.get("LLM_NUM_CTX", "32000"))


def _formater_donnees_pour_llm(donnees: Dict[str, Any], max_lignes: Optional[int] = None) -> str:
    """Formate les données en texte lisible pour le contexte du LLM (taille limitée pour tenir dans 4096 tokens)."""
    max_lignes = max_lignes if max_lignes is not None else LLM_MAX_LIGNES
    colonnes = donnees.get("columns") or []
    data = donnees.get("data") or []
    nb_total = donnees.get("nb_lignes_total") or len(data)
    filename = donnees.get("filename", "le fichier")
    lignes = data[:max_lignes]
    if not colonnes:
        return f"Fichier « {filename} » : {nb_total} ligne(s)."
    header = " | ".join(str(c) for c in colonnes)
    sep = " | ".join("---" for _ in colonnes)
    rows = []
    for row in lignes:
        cells = [str(row.get(c, ""))[:40] for c in colonnes]
        rows.append(" | ".join(cells))
    table = "\n".join([header, sep] + rows)
    if nb_total > max_lignes:
        table += f"\n(... {nb_total - max_lignes} lignes en plus)"
    return (
        f"Donnees fichier (total {nb_total} lignes). Reponds UNIQUEMENT d'apres ce tableau. "
        f"Combien = {nb_total}. Nom present? Cherche dans le tableau.\n"
        f"Colonnes: {', '.join(str(c) for c in colonnes)}\n\n{table}"
    )


def repondre_avec_llm(message: str, donnees: Dict[str, Any]) -> Optional[str]:
    """Répond à une question ouverte en utilisant Ollama (API chat). Retourne None si Ollama indisponible."""
    try:
        contexte = _formater_donnees_pour_llm(donnees)
        logging.info("LLM: envoi contexte longueur=%s caracteres", len(contexte))

        # System court : juste les règles de comportement
        system_msg = (
            "Tu analyses un fichier dont le contenu est fourni par l'utilisateur. "
            "Reponds UNIQUEMENT a partir de ces donnees. Reponds en francais, clairement. "
            "Ne dis jamais que tu n'as pas acces au fichier. "
            "Ne propose jamais d'utiliser Excel ou de contacter quelqu'un."
        )

        # User : données + question ensemble (le modèle voit tout dans le même message)
        user_msg = (
            f"Voici le contenu du fichier :\n\n"
            f"{contexte}\n\n"
            f"Question : {message}"
        )

        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "stream": False,
            "options": {
                "num_ctx": LLM_NUM_CTX,
            },
        }
        req = Request(
            f"{OLLAMA_URL}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            out = json.load(resp)
        # /api/chat renvoie { "message": { "content": "..." } }
        return (out.get("message", {}).get("content") or "").strip()
    except HTTPError as e:
        logging.warning("Ollama erreur HTTP: %s", e)
        return None
    except URLError as e:
        logging.warning("Ollama indisponible (URLError): %s", e)
        return None
    except (OSError, json.JSONDecodeError, KeyError) as e:
        logging.warning("Ollama erreur: %s", e)
        return None


def convert_numpy_types(obj):
    if isinstance(obj, dict):
        return {k: convert_numpy_types(v) for k, v in obj.items()}
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


def _extraire_donnees_pour_db(resultat: Dict[str, Any], filename: str, filepath: Path) -> Optional[Dict[str, Any]]:
    """Extrait colonnes + data (toutes les lignes) au format DB depuis le résultat brut d'upload. Retourne None pour PDF."""
    try:
        if "columns" in resultat and "data" in resultat:
            # CSV
            data = convert_numpy_types(resultat["data"])
            return {
                "filename": filename,
                "columns": resultat["columns"],
                "data": data,
                "nb_lignes_total": len(data) if isinstance(data, list) else 0,
            }
        if "feuille" in resultat:
            # Excel une feuille
            colonnes = resultat.get("colonnes", [])
            lignes = resultat.get("lignes", [])
            data = convert_numpy_types(lignes)
            nb_data = len(data) if isinstance(data, list) else 0
            return {
                "filename": filename,
                "columns": colonnes,
                "data": data,
                "nb_lignes_total": resultat.get("nombre_lignes", nb_data),
            }
        if "donnees" in resultat and resultat["donnees"]:
            # Excel plusieurs feuilles : première feuille
            premiere = next(iter(resultat["donnees"].values()))
            colonnes = premiere.get("colonnes", [])
            lignes = premiere.get("lignes", [])
            data = convert_numpy_types(lignes)
            nb_data = len(data) if isinstance(data, list) else 0
            nb_total = sum(s.get("nombre_lignes", 0) for s in resultat["donnees"].values())
            return {
                "filename": filename,
                "columns": colonnes,
                "data": data,
                "nb_lignes_total": nb_total or nb_data,
            }
    except Exception as e:
        logging.warning("Extraire donnees pour DB: %s", e)
    return None


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"erreur": "Aucun fichier fourni"}), 400

    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"erreur": "Aucun fichier sélectionné"}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        upload_dir = Path(app.config['UPLOAD_FOLDER']).resolve()
        upload_dir.mkdir(parents=True, exist_ok=True)
        filepath = upload_dir / filename
        file.save(str(filepath))

        try:
            # Simple conversion logic
            if filename.lower().endswith(('.xlsx', '.xls')):
                resultat = convertir_excel_en_json(filepath)
            elif filename.lower().endswith('.csv'):
                # Basic CSV support
                df = pd.read_csv(filepath)
                resultat = {
                    "filename": filename,
                    "columns": df.columns.tolist(),
                    "data": df.to_dict(orient='records')
                }
            elif filename.lower().endswith('.pdf'):
                # Basic PDF support
                import pdfplumber
                data = []
                with pdfplumber.open(filepath) as pdf:
                    for i, page in enumerate(pdf.pages):
                        tables = page.extract_tables()
                        text = page.extract_text()
                        data.append({
                            "page": i + 1,
                            "text": text,
                            "tables": tables
                        })
                resultat = {
                    "filename": filename,
                    "type": "pdf",
                    "pages": data
                }
            else:
                return jsonify({"erreur": "Format non supporté"}), 400
            
            # Nettoyer le resultat et renvoyer un chemin absolu pour le chatbot
            resultat_nettoye = convert_numpy_types(resultat)
            assert isinstance(resultat_nettoye, dict), "convert_numpy_types(resultat) doit être un dict"
            file_path_str = str(filepath.resolve())
            resultat_nettoye['fichier_path'] = file_path_str
            resultat_nettoye['filename'] = filename

            # Stocker en base pour réutilisation par le chatbot
            donnees_db = _extraire_donnees_pour_db(resultat, filename, filepath)
            if donnees_db:
                db.save_upload(
                    filename=donnees_db["filename"],
                    file_path=file_path_str,
                    nb_lignes_total=donnees_db["nb_lignes_total"],
                    columns=donnees_db["columns"],
                    data=donnees_db["data"],
                )

            return jsonify(resultat_nettoye)
        except Exception as e:
            logging.error(f"Erreur dans upload_file: {e}", exc_info=True)
            return jsonify({"erreur": str(e), "type": "erreur"}), 500

    return jsonify({"erreur": "Type de fichier non autorisé"}), 400


@app.route('/api/chatbot', methods=['POST'])
def chatbot():
    """Répond aux questions sur les données du fichier."""
    try:
        data = request.get_json() or {}
        message = data.get('message', '').strip()
        fichier_path = data.get('fichier_path')

        if not message:
            return jsonify({"erreur": "Message vide"}), 400

        # Résoudre le chemin du fichier (absolu renvoyé à l'upload, ou recherche dans uploads)
        chemin_fichier = None
        if fichier_path:
            p = Path(fichier_path)
            if p.exists():
                chemin_fichier = p
            else:
                # Fallback : chercher par nom dans le dossier uploads
                upload_dir = Path(app.config['UPLOAD_FOLDER']).resolve()
                candidat = upload_dir / p.name
                if candidat.exists():
                    chemin_fichier = candidat
        if not chemin_fichier:
            logging.warning("Chatbot: fichier_path reçu=%s, fichier introuvable", repr(fichier_path))
            reponse = (
                "Aucun fichier chargé ou fichier introuvable. Analysez d'abord un fichier (Excel ou CSV) "
                "pour poser des questions sur ses données."
            )
            return jsonify({"reponse": reponse})

        # Charger les données depuis la base, sinon depuis le fichier (et sauvegarder en base pour la prochaine fois)
        chemin_str = str(chemin_fichier.resolve())
        donnees = db.get_upload_by_path(chemin_str)
        if not donnees:
            donnees = charger_donnees_fichier(chemin_str)
            if donnees:
                db.save_upload(
                    filename=donnees["filename"],
                    file_path=chemin_str,
                    nb_lignes_total=donnees.get("nb_lignes_total") or len(donnees.get("data") or []),
                    columns=donnees.get("columns") or [],
                    data=donnees.get("data") or [],
                )
        if not donnees:
            logging.warning("Chatbot: donnees vides pour chemin=%s", chemin_fichier)
            reponse = "Impossible de charger les données du fichier. Vérifiez le format (Excel ou CSV)."
            return jsonify({"reponse": reponse})

        nb_lignes = len(donnees.get("data") or [])
        nb_total = donnees.get("nb_lignes_total", 0)
        logging.info("Chatbot: fichier=%s, lignes_ctx=%s, total=%s", donnees.get("filename"), nb_lignes, nb_total)

        # Réponse uniquement par le LLM (Ollama)
        reponse = repondre_avec_llm(message, donnees)
        if reponse is None:
            reponse = (
                "Le modèle (Ollama) n'est pas disponible.\n\n"
                "Sous Windows : lancez l’application **Ollama** depuis le menu Démarrer (elle reste en arrière-plan). "
                "Vous pouvez fermer le terminal « ollama run » ; gardez l’icône Ollama ouverte dans la barre des tâches.\n\n"
                f"Si le modèle n’est pas encore installé, dans un terminal : `ollama run {OLLAMA_MODEL}`"
            )
        return jsonify({"reponse": reponse})
    except Exception as e:
        logging.error(f"Erreur chatbot: {e}", exc_info=True)
        return jsonify({"erreur": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
