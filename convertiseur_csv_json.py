import pandas as pd
import json
import sys
import os

def csv_to_json(csv_file, output_file="output.json", delimiter=","):
    try:
        if not os.path.exists(csv_file):
            print(f"Erreur : le fichier '{csv_file}' est introuvable.")
            return

        # Tentative de lecture avec pandas
        try:
            df = pd.read_csv(csv_file, delimiter=delimiter)
        except Exception:
            # Fallback avec point-virgule si virgule échoue
            df = pd.read_csv(csv_file, delimiter=";")

        json_data = df.to_dict(orient="records")

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=4)

        print(f"Conversion réussie ! Fichier JSON créé : {output_file}")

    except Exception as e:
        print(f"Erreur lors de la conversion CSV : {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Utilisation : python convertiseur_csv_json.py fichier.csv [sortie.json]")
    else:
        csv_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else "output.json"
        csv_to_json(csv_file, output_file)
