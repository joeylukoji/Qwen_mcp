#!/usr/bin/env python3
"""
Test de la fonction générique de conversion Excel vers JSON.
"""

import json
from pathlib import Path
import sys

# Ajouter le répertoire actuel au path pour importer mcp_server
sys.path.insert(0, str(Path(__file__).parent))

from mcp_server import convertir_excel_en_json

def test_conversion_generique():
    """Test de la conversion générique Excel vers JSON."""
    print("Test de conversion Excel vers JSON generique...")
    
    fichier = Path("exemple_notes.xlsx")
    if not fichier.exists():
        print("[ERREUR] Fichier exemple_notes.xlsx non trouve")
        return False
    
    try:
        # Test 1: Conversion de toutes les feuilles
        print("\n[1] Test conversion de toutes les feuilles...")
        resultat = convertir_excel_en_json(fichier)
        print(f"[OK] Conversion reussie")
        print(f"  - Feuilles trouvees: {resultat.get('feuilles', [])}")
        
        # Afficher un apercu
        if 'donnees' in resultat:
            for feuille, contenu in resultat['donnees'].items():
                print(f"  - Feuille '{feuille}': {contenu['nombre_lignes']} lignes, {len(contenu['colonnes'])} colonnes")
        
        # Test 2: Conversion d'une feuille specifique
        print("\n[2] Test conversion d'une feuille specifique...")
        nom_feuille = resultat['feuilles'][0] if 'feuilles' in resultat else None
        if nom_feuille:
            resultat_feuille = convertir_excel_en_json(fichier, feuille=nom_feuille)
            print(f"[OK] Conversion reussie")
            print(f"  - Nombre de lignes: {resultat_feuille['nombre_lignes']}")
            print(f"  - Colonnes: {resultat_feuille['colonnes']}")
            print(f"  - Premiere ligne (apercu): {list(resultat_feuille['lignes'][0].keys())[:3]}...")
        
        # Test 3: Afficher un exemple de JSON
        print("\n[3] Exemple de JSON genere:")
        print(json.dumps(resultat, ensure_ascii=False, indent=2, default=str)[:500] + "...")
        
        print("\n" + "="*50)
        print("[SUCCES] Tous les tests sont passes!")
        print("="*50)
        return True
        
    except Exception as e:
        print(f"\n[ERREUR] Erreur lors du test: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_conversion_generique()
    sys.exit(0 if success else 1)
