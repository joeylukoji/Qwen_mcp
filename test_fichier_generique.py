#!/usr/bin/env python3
"""
Test pour vérifier que le système peut traiter n'importe quel fichier Excel,
pas seulement les fichiers scolaires.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mcp_server import convertir_excel_en_json

def test_fichier_generique():
    """Test avec un fichier Excel générique (inventaire de produits)."""
    print("Test de conversion d'un fichier Excel generique (non scolaire)...")
    print()
    
    fichier = Path("test_generique.xlsx")
    if not fichier.exists():
        print("[ERREUR] Fichier test_generique.xlsx non trouve")
        return False
    
    try:
        # Convertir le fichier en JSON
        print("1. Conversion Excel vers JSON...")
        resultat = convertir_excel_en_json(fichier)
        
        print(f"[OK] Conversion reussie!")
        
        # Gérer les deux formats possibles (avec ou sans feuille spécifiée)
        if 'feuilles' in resultat:
            # Format avec toutes les feuilles
            print(f"   - Feuilles trouvees: {resultat['feuilles']}")
            premiere_feuille = resultat['feuilles'][0]
            donnees_feuille = resultat['donnees'][premiere_feuille]
            print(f"   - Colonnes: {donnees_feuille['colonnes']}")
            print(f"   - Nombre de lignes: {donnees_feuille['nombre_lignes']}")
            lignes = donnees_feuille['lignes']
        else:
            # Format avec une feuille spécifique
            print(f"   - Feuille: {resultat.get('feuille', 'N/A')}")
            print(f"   - Colonnes: {resultat['colonnes']}")
            print(f"   - Nombre de lignes: {resultat['nombre_lignes']}")
            lignes = resultat['lignes']
        
        print()
        
        # Afficher les données
        print("2. Donnees converties en JSON (apercu):")
        apercu = {
            "colonnes": donnees_feuille['colonnes'] if 'feuilles' in resultat else resultat['colonnes'],
            "premiere_ligne": lignes[0] if len(lignes) > 0 else None
        }
        print(json.dumps(apercu, ensure_ascii=False, indent=2, default=str))
        print()
        
        # Vérifier que les données sont correctes
        print("3. Verification des donnees...")
        if len(lignes) > 0:
            premiere_ligne = lignes[0]
            print(f"   - Premiere ligne: {premiere_ligne}")
            
            # Vérifier que les colonnes sont présentes
            colonnes_attendues = ['Produit', 'Prix', 'Stock', 'Categorie']
            if all(col in premiere_ligne for col in colonnes_attendues):
                print("[OK] Toutes les colonnes sont presentes")
            else:
                print("[ERREUR] Colonnes manquantes")
                return False
        else:
            print("[ERREUR] Aucune ligne trouvee")
            return False
        
        print()
        print("="*50)
        print("[SUCCES] Le systeme peut traiter n'importe quel fichier Excel!")
        print("="*50)
        return True
        
    except Exception as e:
        print(f"\n[ERREUR] Erreur lors du test: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_fichier_generique()
    sys.exit(0 if success else 1)
