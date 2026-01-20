#!/usr/bin/env python3
"""
Script de test pour vérifier la connexion à LM Studio.
"""

import asyncio
import json
import sys
from pathlib import Path

# Ajouter le répertoire actuel au path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from mcp_server import appeler_ollama

    async def test_connection():
        """Test de connexion à Ollama."""
        print("Test de connexion à Ollama...")
        print("URL: http://localhost:11434/v1/chat/completions")
        print("Modele: qwen2.5:3b")
        print()

        # Données de test
        donnees_test = {
            "nom": "Test Eleve",
            "classe": "3eme A",
            "notes": {
                "Mathematiques": 12.5,
                "Francais": 14.0,
                "Histoire": 11.0
            },
            "absences": 5
        }

        try:
            print("Envoi des donnees au LLM...")
            resultat = await appeler_ollama(donnees_test)

            print("\n[SUCCES] Connexion reussie!")
            print("\nReponse du LLM:")
            print(json.dumps(resultat, ensure_ascii=False, indent=2))

            return True

        except ConnectionError as e:
            print(f"\n[ERREUR] Impossible de se connecter a LM Studio:")
            print(f"  {str(e)}")
            print("\nAssurez-vous que:")
            print("  1. LM Studio est demarre")
            print("  2. Le modele qwen2.5-vl-3b-instruct est charge")
            print("  3. L'API est activee (Local Server > Start Server)")
            return False
        except Exception as e:
            print(f"\n[ERREUR] Erreur inattendue: {e}")
            import traceback
            traceback.print_exc()
            return False

    if __name__ == "__main__":
        success = asyncio.run(test_connection())
        sys.exit(0 if success else 1)

except ImportError as e:
    print(f"[ERREUR] Import error: {e}")
    print("Installez les dependances avec: pip install -r requirements.txt")
    sys.exit(1)
