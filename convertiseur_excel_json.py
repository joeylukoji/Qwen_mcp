import pandas as pd
import json
import sys
import os

def excel_to_json(excel_file, sheet_name=None, output_file="output.json"):
    try:
        # Vérification de l'existence du fichier
        if not os.path.exists(excel_file):
            print(f"Erreur : le fichier '{excel_file}' est introuvable.")
            return

        # Lecture du fichier Excel
        if sheet_name:
            df = pd.read_excel(excel_file, sheet_name=sheet_name)
        else:
            df = pd.read_excel(excel_file)  # Première feuille par défaut

        # Conversion en JSON (liste d'objets)
        json_data = df.to_dict(orient="records")

        # Sauvegarde dans un fichier JSON
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=4)

        print(f"Conversion réussie ! Fichier JSON créé : {output_file}")

    except Exception as e:
        print(f"Erreur lors de la conversion : {e}")

if __name__ == "__main__":
    # Exemple d'utilisation : python script.py fichier.xlsx [nom_feuille] [sortie.json]
    if len(sys.argv) < 2:
        print("Utilisation : python script.py fichier.xlsx [nom_feuille] [sortie.json]")
    else:
        excel_file = sys.argv[1]
        sheet_name = sys.argv[2] if len(sys.argv) > 2 else None
        output_file = sys.argv[3] if len(sys.argv) > 3 else "output.json"
        excel_to_json(excel_file, sheet_name, output_file)
