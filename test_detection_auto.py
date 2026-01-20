#!/usr/bin/env python3

from mcp_server import convertir_excel_en_json, detecter_ligne_en_tete
from pathlib import Path

fichier = Path("Introduction aux réseaux informatiques - BAC1 IG-1.xlsx")

print("Test de détection automatique de la ligne d'en-tête")
print("="*70)
print()

header_row = detecter_ligne_en_tete(fichier)
print(f"Ligne d'en-tête détectée: {header_row}")
print()

resultat = convertir_excel_en_json(fichier)
feuille_data = list(resultat['donnees'].values())[0]

print(f"Colonnes détectées ({len(feuille_data['colonnes'])}):")
for i, col in enumerate(feuille_data['colonnes'], 1):
    print(f"  {i:2d}. {col}")

print()
print(f"Nombre de lignes: {feuille_data['nombre_lignes']}")
print(f"Ligne en-tête utilisée: {feuille_data['ligne_en_tete']}")
print()

if feuille_data['lignes']:
    print("Première ligne de données:")
    import json
    premiere = feuille_data['lignes'][0]
    print(json.dumps(premiere, indent=2, ensure_ascii=False))
