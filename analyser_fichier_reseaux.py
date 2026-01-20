#!/usr/bin/env python3
"""
Analyse du fichier "Introduction aux réseaux informatiques - BAC1 IG-1.xlsx"
"""

from pathlib import Path
import pandas as pd
import json
from mcp_server import convertir_excel_en_json

fichier = Path("Introduction aux réseaux informatiques - BAC1 IG-1.xlsx")

print("="*70)
print("ANALYSE DU FICHIER EXCEL")
print("="*70)
print()

# Analyser avec header_row=0 (première ligne comme en-tête)
print("1. Analyse avec header_row=0 (premiere ligne comme en-tete)...")
try:
    resultat = convertir_excel_en_json(fichier, header_row=0)
    feuille_data = list(resultat['donnees'].values())[0]
    print(f"   Colonnes detectees: {len(feuille_data['colonnes'])}")
    print(f"   Nombre de lignes: {feuille_data['nombre_lignes']}")
    print(f"   Colonnes: {feuille_data['colonnes'][:5]}...")
    print()
except Exception as e:
    print(f"   Erreur: {e}")
    print()

# Analyser avec header_row=1 (deuxième ligne comme en-tête - probablement correct)
print("2. Analyse avec header_row=1 (deuxieme ligne comme en-tete)...")
try:
    resultat = convertir_excel_en_json(fichier, header_row=1)
    feuille_data = list(resultat['donnees'].values())[0]
    print(f"   Colonnes detectees: {len(feuille_data['colonnes'])}")
    print(f"   Nombre de lignes: {feuille_data['nombre_lignes']}")
    print(f"   Colonnes:")
    for i, col in enumerate(feuille_data['colonnes'], 1):
        print(f"     {i:2d}. {col}")
    print()
    
    if feuille_data['lignes']:
        print("   Premiere ligne de donnees:")
        premiere_ligne = feuille_data['lignes'][0]
        print(json.dumps(premiere_ligne, indent=2, ensure_ascii=False))
    print()
except Exception as e:
    print(f"   Erreur: {e}")
    print()

# Lire directement avec pandas pour voir la structure
print("3. Lecture directe avec pandas...")
try:
    df = pd.read_excel(fichier, header=1)  # Ligne 1 comme en-tête
    print(f"   Colonnes: {list(df.columns)}")
    print(f"   Nombre de lignes: {len(df)}")
    print()
    print("   Apercu des 3 premieres lignes:")
    print(df.head(3).to_string())
    print()
except Exception as e:
    print(f"   Erreur: {e}")

print("="*70)
