#!/usr/bin/env python3

import logging
import os
import json
import asyncio
from pathlib import Path
from typing import Dict, Any
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
import pandas as pd
import numpy as np

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from mcp_server import convertir_excel_en_json, detecter_ligne_en_tete

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['SECRET_KEY'] = os.urandom(24)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'csv'}

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
        filepath = Path(app.config['UPLOAD_FOLDER']) / filename
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
            
            # Nettoyer le resultat
            resultat_nettoye = convert_numpy_types(resultat)
            resultat_nettoye['fichier_path'] = str(filepath)

            return jsonify(resultat_nettoye)
        except Exception as e:
            logging.error(f"Erreur dans upload_file: {e}", exc_info=True)
            return jsonify({"erreur": str(e), "type": "erreur"}), 500

    return jsonify({"erreur": "Type de fichier non autorisé"}), 400

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
