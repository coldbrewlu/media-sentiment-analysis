import os
import json
import re

RAW_DIR = "data/raw"
CLEAN_DIR = "data/cleaned"

def clean_text(text):
    text = re.sub(r"\s+", " ", text)  # Collapse whitespace
    text = re.sub(r"（.*?）", "", text)  # Remove inline references
    text = text.strip()
    return text

def clean_file(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        articles = json.load(f)

    cleaned = []
    for art in articles:
        if len(art.get("content", "")) < 200:
            continue
        cleaned.append({
            "title": art["title"].strip(),
            "date": art["date"],
            "source": art["source"],
            "url": art["url"],
            "content": clean_text(art["content"])
        })

    return cleaned

def process_all():
    os.makedirs(CLEAN_DIR, exist_ok=True)
    for fname in os.listdir(RAW_DIR):
        if fname.endswith(".json"):
            print(f"Cleaning {fname}...")
            cleaned = clean_file(os.path.join(RAW_DIR, fname))
            with open(os.path.join(CLEAN_DIR, fname), "w", encoding="utf-8") as f:
                json.dump(cleaned, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    process_all()
