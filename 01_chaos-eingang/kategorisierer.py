import hashlib
from pathlib import Path

IGNORIERTE_DATEIEN = {"QUELLEN_echte-daten.md"}
TEXT_ENDUNGEN = {".txt", ".md", ".csv", ".log", ".py", ".json", ".xml", ".html"}
VORSCHAU_ZEICHEN = 800


def lade_datei_inventar(ordner: Path) -> list[dict]:
    """Liest alle Dateien im Ordner und gibt Inventar zurück."""
    inventar = []
    for datei in sorted(ordner.iterdir()):
        if not datei.is_file():
            continue
        if datei.name in IGNORIERTE_DATEIEN:
            continue
        if datei.name.startswith("."):
            continue

        inhalt = datei.read_bytes()
        md5 = hashlib.md5(inhalt).hexdigest()

        vorschau = ""
        if datei.suffix.lower() in TEXT_ENDUNGEN:
            try:
                vorschau = inhalt.decode("utf-8", errors="replace")[:VORSCHAU_ZEICHEN]
            except Exception:
                vorschau = ""

        inventar.append({
            "path": datei,
            "name": datei.name,
            "extension": datei.suffix.lower(),
            "content_preview": vorschau,
            "md5": md5,
        })
    return inventar
