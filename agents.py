#!/usr/bin/env python3

import json
import os
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import pandas as pd
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

from mcp_server import convertir_excel_en_json, detecter_ligne_en_tete

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/v1/chat/completions")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
CONTEXTE_MODEL_TOKENS = int(os.getenv("OLLAMA_CONTEXT_SIZE", "32000"))

MIN_LIGNES_ACCES = 100

class AgentIndexeur:
    def __init__(self, chemin_fichier: Path):
        self.chemin_fichier = chemin_fichier
        self.index = {}
        self.df_complet = None
        self.header_row = None

    def indexer_fichier(self) -> Dict[str, Any]:
        try:
            self.header_row = detecter_ligne_en_tete(self.chemin_fichier)
            self.df_complet = pd.read_excel(self.chemin_fichier, header=self.header_row)
            self.df_complet.columns = [str(col).strip() if pd.notna(col) else f"Colonne_{i}"
                                      for i, col in enumerate(self.df_complet.columns)]
            self.index = {
                "nombre_lignes": len(self.df_complet),
                "nombre_colonnes": len(self.df_complet.columns),
                "colonnes": self.df_complet.columns.tolist(),
                "types_colonnes": {col: str(self.df_complet[col].dtype) for col in self.df_complet.columns},
                "statistiques": self._calculer_statistiques(),
                "echantillon": self._creer_echantillon(),
                "valeurs_uniques": self._extraire_valeurs_uniques_importantes()
            }
            return self.index
        except Exception as e:
            raise ValueError(f"Erreur lors de l'indexation: {str(e)}")

    def _calculer_statistiques(self) -> Dict[str, Any]:
        stats = {}
        for col in self.df_complet.select_dtypes(include=['number']).columns:
            if not self.df_complet[col].isna().all():
                stats[col] = {
                    "moyenne": float(self.df_complet[col].mean()),
                    "min": float(self.df_complet[col].min()),
                    "max": float(self.df_complet[col].max()),
                    "mediane": float(self.df_complet[col].median()),
                    "ecart_type": float(self.df_complet[col].std()) if len(self.df_complet[col].dropna()) > 1 else 0,
                    "total_valides": int(self.df_complet[col].notna().sum()),
                    "total_manquants": int(self.df_complet[col].isna().sum())
                }
        for col in self.df_complet.select_dtypes(include=['object']).columns:
            if not self.df_complet[col].isna().all():
                stats[col] = {
                    "total_valides": int(self.df_complet[col].notna().sum()),
                    "total_manquants": int(self.df_complet[col].isna().sum()),
                    "nombre_valeurs_uniques": int(self.df_complet[col].nunique())
                }
        return stats

    def _creer_echantillon(self, n_lignes: int = 10) -> List[Dict[str, Any]]:
        total = len(self.df_complet)
        if total <= n_lignes:
            echantillon_df = self.df_complet
        else:
            debut = self.df_complet.head(n_lignes // 3)
            milieu = self.df_complet.iloc[total // 2:total // 2 + n_lignes // 3]
            fin = self.df_complet.tail(n_lignes // 3)
            echantillon_df = pd.concat([debut, milieu, fin]).drop_duplicates()
        echantillon = echantillon_df.to_dict(orient='records')
        return self._nettoyer_nan(echantillon)

    def _extraire_valeurs_uniques_importantes(self, max_valeurs: int = 20) -> Dict[str, List[Any]]:
        valeurs_uniques = {}
        for col in self.df_complet.columns:
            if self.df_complet[col].dtype == 'object':
                uniques = self.df_complet[col].dropna().unique().tolist()[:max_valeurs]
                valeurs_uniques[col] = uniques
        return valeurs_uniques

    def _nettoyer_nan(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: self._nettoyer_nan(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._nettoyer_nan(item) for item in obj]
        elif pd.isna(obj) if hasattr(pd, 'isna') else (obj != obj if isinstance(obj, float) else False):
            return None
        elif isinstance(obj, float) and (obj != obj):
            return None
        return obj

    def obtenir_lignes_par_criteres(self, criteres: Dict[str, Any]) -> List[Dict[str, Any]]:
        if self.df_complet is None:
            raise ValueError("Le fichier doit être indexé d'abord")
        df_filtre = self.df_complet.copy()
        for col, valeur in criteres.items():
            if col not in df_filtre.columns:
                continue
            if isinstance(valeur, dict):
                if "min" in valeur:
                    df_filtre = df_filtre[df_filtre[col] >= valeur["min"]]
                if "max" in valeur:
                    df_filtre = df_filtre[df_filtre[col] <= valeur["max"]]
                if "contains" in valeur:
                    search_text = str(valeur["contains"]).lower()
                    df_filtre = df_filtre[
                        df_filtre[col].astype(str).str.lower().str.contains(search_text, na=False, regex=False)
                    ]
            else:
                if df_filtre[col].dtype == 'object':
                    df_filtre = df_filtre[df_filtre[col].astype(str).str.lower() == str(valeur).lower()]
                else:
                    df_filtre = df_filtre[df_filtre[col] == valeur]
        lignes = df_filtre.to_dict(orient='records')
        return self._nettoyer_nan(lignes)

    def rechercher_par_nom(self, nom_recherche: str, colonnes_nom: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        if self.df_complet is None:
            raise ValueError("Le fichier doit être indexé d'abord")
        if colonnes_nom is None:
            colonnes_nom = []
            mots_cles = ['nom', 'name', 'étudiant', 'student', 'élève', 'eleve']
            for col in self.df_complet.columns:
                col_lower = str(col).lower()
                if any(mot in col_lower for mot in mots_cles):
                    colonnes_nom.append(col)
            if not colonnes_nom:
                for col in self.df_complet.columns:
                    if self.df_complet[col].dtype == 'object':
                        colonnes_nom.append(col)
                        break
        if not colonnes_nom:
            return []
        df_filtre = self.df_complet.copy()
        nom_lower = nom_recherche.lower().strip()
        masque = pd.Series([False] * len(df_filtre))
        for col in colonnes_nom:
            if col in df_filtre.columns:
                masque |= df_filtre[col].astype(str).str.lower().str.contains(nom_lower, na=False, regex=False)
        df_filtre = df_filtre[masque]
        lignes = df_filtre.to_dict(orient='records')
        return self._nettoyer_nan(lignes)

    def obtenir_lignes_par_indices(self, indices: List[int]) -> List[Dict[str, Any]]:
        if self.df_complet is None:
            raise ValueError("Le fichier doit être indexé d'abord")
        lignes = self.df_complet.iloc[indices].to_dict(orient='records')
        return self._nettoyer_nan(lignes)


class AgentChercheur:
    def __init__(self, index: Dict[str, Any], df_complet: pd.DataFrame):
        self.index = index
        self.df_complet = df_complet

    def _detecter_nom_dans_question(self, question: str) -> Optional[str]:
        question_lower = question.lower()
        patterns = [
            r"nom (?:de |d'|du )?([A-Z][A-Z\s]+)",
            r"([A-Z][A-Z\s]{5,}) (?:a|ont|ses|ses notes|ses résultats)",
            r"(?:les |ses |ses )?(?:notes|résultats|données|informations) (?:de |d'|du )?([A-Z][A-Z\s]+)",
            r"([A-Z][A-Z\s]{5,}) (?:a|ont) (?:les |ses )?(?:notes|résultats)",
            r"étudiant (?:nommé |appelé )?([A-Z][A-Z\s]+)",
            r"([A-Z][A-Z\s]{5,}) (?:est|était)",
        ]
        import re
        for pattern in patterns:
            match = re.search(pattern, question)
            if match:
                nom = match.group(1).strip()
                mots_a_exclure = ['les', 'ses', 'ses notes', 'ses résultats', 'a', 'ont', 'est', 'était']
                for mot in mots_a_exclure:
                    nom = nom.replace(mot, '').strip()
                if len(nom) > 3:
                    return nom
        mots = question.split()
        noms_candidats = [m for m in mots if m.isupper() and len(m) > 3]
        if noms_candidats:
            nom = ' '.join(noms_candidats[:3])
            return nom
        return None

    async def identifier_donnees_pertinentes(self, question: str) -> Dict[str, Any]:
        nom_detecte = self._detecter_nom_dans_question(question)
        if nom_detecte:
            print(f"[AGENT CHERCHEUR] Nom détecté automatiquement: {nom_detecte}")
            return {
                "colonnes_pertinentes": self.index["colonnes"],
                "criteres_filtrage": {},
                "recherche_nom": nom_detecte,
                "max_lignes": 1,
                "strategie": "recherche_nom"
            }
        if not HTTPX_AVAILABLE:
            return {
                "colonnes_pertinentes": self.index["colonnes"],
                "criteres_filtrage": {},
                "max_lignes": max(1000, MIN_LIGNES_ACCES),
                "strategie": "toutes_colonnes"
            }
        contexte_index = {
            "nombre_lignes": self.index["nombre_lignes"],
            "nombre_colonnes": self.index["nombre_colonnes"],
            "colonnes": self.index["colonnes"][:50],
            "statistiques": {k: v for k, v in list(self.index["statistiques"].items())[:20]},
            "valeurs_uniques": {k: v[:10] for k, v in list(self.index["valeurs_uniques"].items())[:10]}
        }
        prompt = f"""Tu es un agent spécialisé dans l'identification de données pertinentes.

INDEX DU FICHIER EXCEL:
{json.dumps(contexte_index, ensure_ascii=False, indent=2)}

QUESTION DE L'UTILISATEUR:
{question}

TÂCHE: Identifie quelles colonnes et quelles lignes sont pertinentes pour répondre à cette question.

IMPORTANT: Si la question mentionne un nom spécifique (étudiant, personne, etc.), utilise OBLIGATOIREMENT "recherche_nom" dans la stratégie.
Si la question demande des informations sur une personne spécifique (notes, résultats, etc.), utilise "recherche_nom".
NE JAMAIS utiliser "echantillon" si la question concerne une personne spécifique.

Réponds UNIQUEMENT avec un JSON dans ce format:
{{
  "colonnes_pertinentes": ["colonne1", "colonne2", ...],
  "criteres_filtrage": {{
    "colonne": "valeur" ou {{"min": X, "max": Y}} ou {{"contains": "texte"}}
  }},
  "recherche_nom": "nom à rechercher" (si la question mentionne un nom spécifique),
  "max_lignes": nombre_maximum_de_lignes_à_extraire,
  "strategie": "filtrage" | "recherche_nom" | "echantillon" | "toutes_colonnes"
}}

Si la question mentionne un nom spécifique, utilise OBLIGATOIREMENT "recherche_nom" avec le nom dans "recherche_nom".
Si la question nécessite TOUTES les données, mets "toutes_colonnes" dans strategie.
Si la question nécessite un filtrage spécifique, utilise "filtrage" avec criteres_filtrage.
Si la question nécessite un échantillon, utilise "echantillon" avec max_lignes (minimum {MIN_LIGNES_ACCES} lignes)."""
        try:
            async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
                payload = {
                    "model": OLLAMA_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Tu es un expert en analyse de données. Tu identifies les données pertinentes pour répondre à des questions."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": 0.3,
                    "stream": False
                }
                response = await client.post(OLLAMA_URL, json=payload)
                response.raise_for_status()
                result = response.json()
                reponse_text = result.get('choices', [{}])[0].get('message', {}).get('content', '{}')
                try:
                    if '{' in reponse_text:
                        json_start = reponse_text.find('{')
                        json_end = reponse_text.rfind('}') + 1
                        reponse_json = json.loads(reponse_text[json_start:json_end])
                    else:
                        reponse_json = json.loads(reponse_text)
                except:
                    reponse_json = {
                        "colonnes_pertinentes": self.index["colonnes"],
                        "criteres_filtrage": {},
                        "max_lignes": max(1000, MIN_LIGNES_ACCES),
                        "strategie": "toutes_colonnes"
                    }
                if int(reponse_json.get("max_lignes", 0)) < MIN_LIGNES_ACCES and reponse_json.get("strategie") != "recherche_nom":
                    reponse_json["max_lignes"] = MIN_LIGNES_ACCES
                return reponse_json
        except Exception as e:
            print(f"[AGENT CHERCHEUR] Erreur: {e}, utilisation du fallback")
            return {
                "colonnes_pertinentes": self.index["colonnes"],
                "criteres_filtrage": {},
                "max_lignes": max(1000, MIN_LIGNES_ACCES),
                "strategie": "toutes_colonnes"
            }


class AgentAnalyseur:
    def __init__(self, index: Dict[str, Any]):
        self.index = index

    async def analyser(self, question: str, donnees_pertinentes: List[Dict[str, Any]],
                      plan_extraction: Dict[str, Any]) -> str:
        if not HTTPX_AVAILABLE:
            return "Erreur: httpx n'est pas disponible."
        is_recherche_specifique = len(donnees_pertinentes) <= 5 and plan_extraction.get("strategie") == "recherche_nom"

        if is_recherche_specifique:
            donnees_etudiant = donnees_pertinentes[0] if donnees_pertinentes else {}
            colonnes_notes = []
            colonnes_autres = []
            for col, val in donnees_etudiant.items():
                col_lower = str(col).lower()
                if any(mot in col_lower for mot in ['note', 'score', 'moyenne', 'point', 'examen', 'test', 'devoir', 'td', 'tp', 'cc']):
                    colonnes_notes.append((col, val))
                else:
                    colonnes_autres.append((col, val))
            format_donnees = []
            format_donnees.append("=== INFORMATIONS GÉNÉRALES ===")
            for col, val in colonnes_autres[:15]:
                if val is not None and val != "":
                    format_donnees.append(f"{col}: {val}")
            format_donnees.append("\n=== NOTES ===")
            if colonnes_notes:
                for col, val in colonnes_notes:
                    if val is not None and val != "":
                        format_donnees.append(f"{col}: {val}")
            else:
                format_donnees.append("Aucune note trouvée dans les colonnes")
            if len(colonnes_autres) > 15:
                format_donnees.append(f"\n(Note: {len(colonnes_autres) - 15} autres colonnes disponibles)")
            donnees_formatees = "\n".join(format_donnees)
            if len(donnees_formatees) > 8000:
                donnees_formatees = donnees_formatees[:8000] + "\n...(données tronquées)"
            prompt = f"""Tu es un assistant expert en analyse de données Excel.

DONNÉES COMPLÈTES DE L'ÉTUDIANT TROUVÉ:
{donnees_formatees}

QUESTION DE L'UTILISATEUR:
{question}

INSTRUCTIONS IMPORTANTES:
1. Utilise UNIQUEMENT les données ci-dessus pour répondre
2. Si la question demande les notes, liste TOUTES les notes avec leurs valeurs exactes
3. Si la question demande des statistiques (moyenne, total, etc.), calcule-les à partir des notes disponibles
4. Sois précis et utilise les valeurs exactes des données
5. Si une information n'est pas disponible dans les données, dis-le clairement
6. Réponds en français de manière claire et structurée"""
        else:
            lignes_a_envoyer = max(MIN_LIGNES_ACCES, len(donnees_pertinentes))
            donnees_finales = donnees_pertinentes[:lignes_a_envoyer] if len(donnees_pertinentes) > lignes_a_envoyer else donnees_pertinentes
            contexte_compact = {
                "index_global": {
                    "nombre_lignes_total": self.index["nombre_lignes"],
                    "nombre_colonnes": self.index["nombre_colonnes"],
                    "colonnes": self.index["colonnes"],
                    "statistiques_completes": self.index["statistiques"]
                },
                "donnees_pertinentes": {
                    "nombre_lignes": len(donnees_finales),
                    "lignes": donnees_finales
                },
                "plan_extraction": plan_extraction
            }
            max_chars_conservateur = 60000
            if CONTEXTE_MODEL_TOKENS < 20000:
                max_chars = int(CONTEXTE_MODEL_TOKENS * 3 * 0.50)
            else:
                max_chars = max_chars_conservateur
            contexte_json = json.dumps(contexte_compact, ensure_ascii=False, indent=1, default=str)
            if len(contexte_json) > max_chars:
                lignes_min = min(MIN_LIGNES_ACCES, len(donnees_finales))
                donnees_tronquees = donnees_finales[:lignes_min]
                index_simplifie = {
                    "nombre_lignes_total": contexte_compact["index_global"]["nombre_lignes_total"],
                    "nombre_colonnes": contexte_compact["index_global"]["nombre_colonnes"],
                    "colonnes": contexte_compact["index_global"]["colonnes"][:30],
                    "statistiques_completes": {}
                }
                contexte_compact["index_global"] = index_simplifie
                contexte_compact["donnees_pertinentes"]["lignes"] = donnees_tronquees
                contexte_compact["donnees_pertinentes"]["message"] = f"Échantillon de {len(donnees_tronquees)} lignes sur {len(donnees_finales)} totales"
                contexte_json = json.dumps(contexte_compact, ensure_ascii=False, indent=1, default=str)
                if len(contexte_json) > max_chars:
                    donnees_tronquees = donnees_finales[:min(MIN_LIGNES_ACCES, len(donnees_finales))]
                    contexte_compact["donnees_pertinentes"]["lignes"] = donnees_tronquees
                    contexte_json = json.dumps(contexte_compact, ensure_ascii=False, indent=1, default=str)
            prompt = f"""Tu es un assistant expert en analyse de données Excel.

CONTEXTE GLOBAL DU FICHIER:
{json.dumps(contexte_compact["index_global"], ensure_ascii=False, indent=2)}

DONNÉES PERTINENTES EXTRACTES (pour cette question spécifique):
{json.dumps(contexte_compact["donnees_pertinentes"], ensure_ascii=False, indent=2)}

QUESTION DE L'UTILISATEUR:
{question}

TÂCHE: Analyse les données et réponds à la question de manière claire et précise.
Utilise les statistiques globales ET les données pertinentes pour donner une réponse complète.
Si des calculs sont nécessaires, utilise les statistiques complètes du fichier."""

        try:
            async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
                if is_recherche_specifique:
                    system_content = """Tu es un assistant expert en analyse de données Excel.
RÈGLES STRICTES:
1. Utilise UNIQUEMENT les données fournies dans le message utilisateur
2. Ne jamais inventer ou deviner des valeurs
3. Si une information n'est pas dans les données, dis "Non disponible dans les données"
4. Pour les notes, liste-les avec leurs valeurs exactes telles qu'elles apparaissent
5. Sois précis et factuel, pas de suppositions
6. Réponds en français de manière claire et structurée"""
                else:
                    system_content = """Tu es un assistant intelligent qui aide à analyser des fichiers Excel.
Tu reçois un index global du fichier (statistiques complètes) et des données pertinentes extraites pour répondre à une question spécifique.
Utilise les statistiques globales pour les calculs sur TOUTES les données.
Utilise les données pertinentes pour les détails et exemples spécifiques.
Réponds de manière claire, professionnelle et précise.
Ne jamais inventer de données."""
                temperature = 0.3 if is_recherche_specifique else 0.5
                payload = {
                    "model": OLLAMA_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": system_content
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": temperature,
                    "stream": False
                }
                response = await client.post(OLLAMA_URL, json=payload)
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
        except httpx.HTTPStatusError as e:
            return f"Erreur lors de l'appel au LLM (HTTP {e.response.status_code}): {e.response.text[:500]}"
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"[AGENT ANALYSEUR] Erreur: {error_details}")
            return f"Erreur lors de l'analyse: {str(e)}"


async def analyser_avec_agents(chemin_fichier: Path, question: str) -> str:
    try:
        print("[AGENT INDEXEUR] Indexation du fichier...")
        indexeur = AgentIndexeur(chemin_fichier)
        index = indexeur.indexer_fichier()
        print(f"[AGENT INDEXEUR] Fichier indexé: {index['nombre_lignes']} lignes, {index['nombre_colonnes']} colonnes")
        print("[AGENT CHERCHEUR] Identification des données pertinentes...")
        chercheur = AgentChercheur(index, indexeur.df_complet)
        plan_extraction = await chercheur.identifier_donnees_pertinentes(question)
        print(f"[AGENT CHERCHEUR] Plan: {plan_extraction['strategie']}, {len(plan_extraction.get('colonnes_pertinentes', []))} colonnes")
        donnees_pertinentes = []
        question_lower = question.lower()
        mots_question = question.split()
        noms_majuscules = [m for m in mots_question if m.isupper() and len(m) > 3]
        if noms_majuscules and plan_extraction["strategie"] != "recherche_nom":
            nom_candidat = ' '.join(noms_majuscules[:3])
            print(f"[EXTRACTION] Détection de nom dans la question, passage en mode recherche: {nom_candidat}")
            plan_extraction["strategie"] = "recherche_nom"
            plan_extraction["recherche_nom"] = nom_candidat
        if plan_extraction["strategie"] == "recherche_nom":
            nom_recherche = plan_extraction.get("recherche_nom", "")
            if nom_recherche:
                print(f"[EXTRACTION] Recherche du nom: {nom_recherche}")
                donnees_pertinentes = indexeur.rechercher_par_nom(nom_recherche)
                if not donnees_pertinentes:
                    print(f"[EXTRACTION] Aucun résultat trouvé pour: {nom_recherche}")
                    mots_nom = nom_recherche.split()
                    if len(mots_nom) > 1:
                        for mot in mots_nom:
                            if len(mot) > 3:
                                print(f"[EXTRACTION] Essai avec le mot: {mot}")
                                donnees_pertinentes = indexeur.rechercher_par_nom(mot)
                                if donnees_pertinentes:
                                    break
                    if not donnees_pertinentes and plan_extraction.get("criteres_filtrage"):
                        donnees_pertinentes = indexeur.obtenir_lignes_par_criteres(plan_extraction.get("criteres_filtrage", {}))
                if not donnees_pertinentes:
                    return f"Aucun étudiant trouvé avec le nom '{nom_recherche}'. Veuillez vérifier l'orthographe du nom."
            else:
                donnees_pertinentes = indexeur.obtenir_lignes_par_criteres(plan_extraction.get("criteres_filtrage", {}))
        elif plan_extraction["strategie"] == "filtrage":
            donnees_pertinentes = indexeur.obtenir_lignes_par_criteres(plan_extraction.get("criteres_filtrage", {}))
        elif plan_extraction["strategie"] == "echantillon":
            max_lignes = max(MIN_LIGNES_ACCES, min(int(plan_extraction.get("max_lignes", 1000)), int(index.get("nombre_lignes", 0))))
            indices = list(range(0, int(index.get("nombre_lignes", 0)), max(1, int(index.get("nombre_lignes", 0)) // max_lignes)))[:max_lignes]
            donnees_pertinentes = indexeur.obtenir_lignes_par_indices(indices)
        else:
            max_lignes = max(MIN_LIGNES_ACCES, min(int(plan_extraction.get("max_lignes", 5000)), int(index.get("nombre_lignes", 0))))
            if int(index.get("nombre_lignes", 0)) <= max_lignes:
                donnees_pertinentes = indexeur.obtenir_lignes_par_indices(list(range(index["nombre_lignes"])))
            else:
                indices = list(range(0, int(index.get("nombre_lignes", 0)), max(1, int(index.get("nombre_lignes", 0)) // max_lignes)))[:max_lignes]
                donnees_pertinentes = indexeur.obtenir_lignes_par_indices(indices)
        if len(donnees_pertinentes) < MIN_LIGNES_ACCES and int(index.get("nombre_lignes", 0)) >= MIN_LIGNES_ACCES and plan_extraction.get("strategie") != "recherche_nom":
            manque = MIN_LIGNES_ACCES - len(donnees_pertinentes)
            indices_deja_utilises = set()
            indices_supplementaires = []
            for i in range(min(manque, index["nombre_lignes"])):
                indices_supplementaires.append(i)
            if indices_supplementaires:
                donnees_supplementaires = indexeur.obtenir_lignes_par_indices(indices_supplementaires)
                donnees_pertinentes = donnees_pertinentes + donnees_supplementaires[:manque]
        if plan_extraction.get("colonnes_pertinentes") and len(plan_extraction["colonnes_pertinentes"]) < len(index["colonnes"]):
            colonnes_pertinentes = plan_extraction["colonnes_pertinentes"]
            donnees_pertinentes = [
                {k: v for k, v in ligne.items() if k in colonnes_pertinentes}
                for ligne in donnees_pertinentes
            ]
        print(f"[EXTRACTION] {len(donnees_pertinentes)} lignes extraites")
        print("[AGENT ANALYSEUR] Génération de l'analyse...")
        analyseur = AgentAnalyseur(index)
        reponse = await analyseur.analyser(question, donnees_pertinentes, plan_extraction)
        print("[AGENT ANALYSEUR] Analyse terminée")
        return reponse
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"[ERREUR MULTI-AGENTS] {error_details}")
        return f"Erreur lors de l'analyse multi-agents: {str(e)}"
