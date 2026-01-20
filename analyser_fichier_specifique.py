#!/usr/bin/env python3
"""
Script pour analyser un fichier Excel spécifique.
"""

import pandas as pd
from pathlib import Path
import json
import sys

fichier_nom = "Introduction aux réseaux informatiques - BAC1 IG-1.xlsx"
fichier = Path(fichier_nom)

if not fichier.exists():
    print(f"[ERREUR] Fichier '{fichier_nom}' non trouve dans le repertoire actuel.")
    print(f"Repertoire actuel: {Path.cwd()}")
    print("\nFichiers Excel trouves:")
    for f in Path('.').glob('*.xlsx'):
        print(f"  - {f.name}")
    sys.exit(1)

print("="*70)
print(f"Analyse du fichier: {fichier_nom}")
print("="*70)
print()

try:
    # Lire le fichier Excel
    excel_file = pd.ExcelFile(fichier)
    print(f"Feuilles trouvees: {excel_file.sheet_names}")
    print()
    
    # Analyser chaque feuille
    for sheet_name in excel_file.sheet_names:
        print(f"--- Feuille: {sheet_name} ---")
        df = pd.read_excel(excel_file, sheet_name=sheet_name)
        
        print(f"Colonnes ({len(df.columns)}):")
        for i, col in enumerate(df.columns, 1):
            print(f"  {i:2d}. {col}")
        print()
        
        print(f"Nombre de lignes: {len(df)}")
        print()
        
        print("Apercu des 5 premieres lignes:")
        print(df.head(5).to_string())
        print()
        
        # Informations sur les types de données
        print("Types de donnees:")
        for col in df.columns:
            dtype = df[col].dtype
            non_null = df[col].notna().sum()
            print(f"  {col}: {dtype} ({non_null}/{len(df)} valeurs non-null)")
        print()
        print("="*70)
        print()
        
except Exception as e:
    print(f"[ERREUR] Erreur lors de la lecture: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
