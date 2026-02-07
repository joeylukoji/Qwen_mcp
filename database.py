#!/usr/bin/env python3
"""
Stockage des données uploadées en base SQLite pour les réutiliser dans le chatbot.
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

# Fichier DB dans le répertoire du projet
DB_PATH = Path(__file__).resolve().parent / "data" / "uploads.db"

logger = logging.getLogger(__name__)


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Crée la table des uploads si elle n'existe pas."""
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                file_path TEXT NOT NULL UNIQUE,
                nb_lignes_total INTEGER NOT NULL,
                columns_json TEXT NOT NULL,
                data_json TEXT NOT NULL,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    finally:
        conn.close()


def save_upload(
    filename: str,
    file_path: str,
    nb_lignes_total: int,
    columns: List[Any],
    data: List[Dict[str, Any]],
) -> None:
    """Enregistre ou met à jour les données d'un fichier dans la base.
    Les listes columns et data doivent contenir des types JSON-serializables (après convert_numpy_types côté appelant).
    """
    init_db()
    columns_json = json.dumps(columns, ensure_ascii=False, default=str)
    data_json = json.dumps(data, ensure_ascii=False, default=str)
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO uploads (filename, file_path, nb_lignes_total, columns_json, data_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                filename = excluded.filename,
                nb_lignes_total = excluded.nb_lignes_total,
                columns_json = excluded.columns_json,
                data_json = excluded.data_json,
                uploaded_at = CURRENT_TIMESTAMP
            """,
            (filename, file_path, nb_lignes_total, columns_json, data_json),
        )
        conn.commit()
        logger.info("DB: enregistrement fichier %s (%s lignes)", filename, nb_lignes_total)
    finally:
        conn.close()


def get_upload_by_path(file_path: str) -> Optional[Dict[str, Any]]:
    """
    Récupère les données d'un upload par chemin de fichier.
    Retourne un dict au format { filename, columns, data, nb_lignes_total } ou None.
    """
    init_db()
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT filename, nb_lignes_total, columns_json, data_json FROM uploads WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        if row is None:
            return None
        return {
            "filename": row["filename"],
            "columns": json.loads(row["columns_json"]),
            "data": json.loads(row["data_json"]),
            "nb_lignes_total": row["nb_lignes_total"],
        }
    finally:
        conn.close()


def list_uploads() -> List[Dict[str, Any]]:
    """Liste tous les enregistrements (filename, file_path, nb_lignes_total, uploaded_at)."""
    init_db()
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT filename, file_path, nb_lignes_total, uploaded_at FROM uploads ORDER BY uploaded_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
