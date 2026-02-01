import json
import sys
import os

def pdf_to_json(pdf_file, output_file="output.json"):
    try:
        import pdfplumber
    except ImportError:
        print("Erreur : La bibliothèque 'pdfplumber' est requise pour la conversion PDF.")
        print("Installez-la avec : pip install pdfplumber")
        return

    try:
        if not os.path.exists(pdf_file):
            print(f"Erreur : le fichier '{pdf_file}' est introuvable.")
            return

        data = []
        with pdfplumber.open(pdf_file) as pdf:
            for i, page in enumerate(pdf.pages):
                tables = page.extract_tables()
                text = page.extract_text()
                
                page_data = {
                    "page": i + 1,
                    "text": text,
                    "tables": tables
                }
                data.append(page_data)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        print(f"Conversion réussie ! Fichier JSON créé : {output_file}")

    except Exception as e:
        print(f"Erreur lors de la conversion PDF : {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Utilisation : python convertiseur_pdf_json.py fichier.pdf [sortie.json]")
    else:
        pdf_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else "output.json"
        pdf_to_json(pdf_file, output_file)
