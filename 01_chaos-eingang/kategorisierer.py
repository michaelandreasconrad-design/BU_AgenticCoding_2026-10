import argparse
import hashlib
from pathlib import Path
import json
import os
import sys
import anthropic
import shutil

IGNORIERTE_DATEIEN = {"QUELLEN_echte-daten.md"}
TEXT_ENDUNGEN = {".txt", ".md", ".csv", ".log", ".py", ".json", ".xml", ".html"}
VORSCHAU_ZEICHEN = 800

GUELTIGE_KATEGORIEN = {
    "Rechnungen", "Briefe", "Vertraege", "Notizen",
    "Fotos", "Screenshots", "Daten", "Duplikate", "Sonstiges",
}

SYSTEM_PROMPT = """\
Du bist ein Datei-Kategorisierer. Du erhältst eine Liste von Dateien mit Name,
Endung und (für Textdateien) einem Inhalts-Vorschau. Gib als Antwort ausschließlich
ein JSON-Objekt zurück: {"Dateiname": "Kategorie", ...}.

Erlaubte Kategorien:
- Rechnungen: Rechnungen, Belege, Bestellbestätigungen, Kontoauszüge
- Briefe: Briefe, E-Mails, Anschreiben, Behördenschreiben
- Vertraege: Mietverträge, Kaufverträge, Vereinbarungen
- Notizen: Besprechungsnotizen, To-do-Listen, Memos
- Fotos: Fotos, Bilder (JPG, JPEG, PNG die kein Screenshot sind)
- Screenshots: Screenshots von Bildschirmen, App-UIs
- Daten: Tabellen, CSV-Dateien mit Messdaten oder Finanzdaten
- Sonstiges: alles, was nicht eindeutig zuzuordnen ist

Antworte NUR mit dem JSON-Objekt, ohne Erklärung oder Markdown-Blöcke.\
"""


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


def klassifiziere_mit_claude(inventar: list[dict]) -> dict[str, str]:
    """Sendet das Inventar an Claude und gibt ein Mapping Dateiname→Kategorie zurück."""
    if not inventar:
        return {}

    zeilen = []
    for eintrag in inventar:
        zeile = f"- {eintrag['name']} ({eintrag['extension']})"
        if eintrag["content_preview"]:
            zeile += f"\n  Inhalt: {eintrag['content_preview'][:400]}"
        zeilen.append(zeile)

    nutzerprompt = "Bitte kategorisiere diese Dateien:\n\n" + "\n".join(zeilen)

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-opus-5-5",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": nutzerprompt}],
    )

    rohtext = response.content[0].text.strip()
    # JSON aus eventuellen Markdown-Codeblöcken befreien
    if rohtext.startswith("```"):
        rohtext = "\n".join(rohtext.split("\n")[1:])
    rohtext = rohtext.rstrip("`").strip()

    try:
        mapping = json.loads(rohtext)
    except json.JSONDecodeError:
        # Fallback: alle Dateien → Sonstiges
        return {e["name"]: "Sonstiges" for e in inventar}

    # Alle Dateien mit Sonstiges initialisieren, dann mit Claude-Klassifikationen überschreiben
    result = {e["name"]: "Sonstiges" for e in inventar}
    result.update({
        name: (kat if kat in GUELTIGE_KATEGORIEN else "Sonstiges")
        for name, kat in mapping.items()
    })
    return result


def finde_duplikate(inventar: list[dict]) -> set[str]:
    """Gibt Dateinamen zurück, die byte-identische Duplikate eines anderen Eintrags sind."""
    gesehen: dict[str, str] = {}  # md5 → erster Dateiname
    duplikate: set[str] = set()
    for eintrag in inventar:
        md5 = eintrag["md5"]
        if md5 in gesehen:
            duplikate.add(eintrag["name"])
        else:
            gesehen[md5] = eintrag["name"]
    return duplikate


def _eindeutiger_zielpfad(zielordner: Path, dateiname: str) -> Path:
    """Gibt einen Pfad zurück, der noch nicht existiert (fügt _2, _3 ... ein)."""
    ziel = zielordner / dateiname
    if not ziel.exists():
        return ziel
    stamm = ziel.stem
    suffix = ziel.suffix
    zaehler = 2
    while True:
        kandidat = zielordner / f"{stamm}_{zaehler}{suffix}"
        if not kandidat.exists():
            return kandidat
        zaehler += 1


def plane_verschiebungen(
    inventar: list[dict],
    mapping: dict[str, str],
    duplikate: set[str],
    basisordner: Path,
) -> list[dict]:
    """Erstellt einen Aktionsplan, ohne Dateien zu verschieben."""
    plan = []
    for eintrag in inventar:
        name = eintrag["name"]
        kategorie = "Duplikate" if name in duplikate else mapping.get(name, "Sonstiges")
        zielordner = basisordner / kategorie
        ziel = _eindeutiger_zielpfad(zielordner, name)
        aktion = "duplikat" if name in duplikate else "verschieben"
        plan.append({
            "von": name,
            "nach": str(ziel),
            "kategorie": kategorie,
            "aktion": aktion,
        })
    return plan


def fuehre_plan_aus(plan: list[dict], basisordner: Path) -> None:
    """Verschiebt Dateien gemäß Plan."""
    erstellte_ordner: set[Path] = set()
    for aktion in plan:
        ziel = Path(aktion["nach"])
        if ziel.parent not in erstellte_ordner:
            ziel.parent.mkdir(parents=True, exist_ok=True)
            erstellte_ordner.add(ziel.parent)
        quelle = basisordner / aktion["von"]
        shutil.move(str(quelle), str(ziel))


def main():
    parser = argparse.ArgumentParser(description="KI-Datei-Kategorisierer")
    parser.add_argument("ordner", nargs="?", default=".", help="Zu sortierender Ordner")
    parser.add_argument("--execute", action="store_true", help="Dateien tatsächlich verschieben")
    args = parser.parse_args()

    basisordner = Path(args.ordner).resolve()
    if not basisordner.is_dir():
        print(f"Fehler: '{basisordner}' ist kein Ordner.", file=sys.stderr)
        sys.exit(1)

    print(f"Lese Dateien aus: {basisordner}")
    inventar = lade_datei_inventar(basisordner)
    if not inventar:
        print("Keine Dateien gefunden.")
        return

    print(f"{len(inventar)} Dateien gefunden. Sende an Claude zur Klassifikation...")
    try:
        mapping = klassifiziere_mit_claude(inventar)
    except anthropic.AuthenticationError:
        print("Fehler: ANTHROPIC_API_KEY nicht gesetzt oder ungültig.", file=sys.stderr)
        sys.exit(1)

    duplikate = finde_duplikate(inventar)
    if duplikate:
        print(f"Duplikate gefunden: {', '.join(duplikate)}")

    plan = plane_verschiebungen(inventar, mapping, duplikate, basisordner)

    print("\n--- Geplante Aktionen ---")
    for aktion in plan:
        symbol = "📋" if not args.execute else "→"
        print(f"  {symbol} {aktion['von']} → {aktion['kategorie']}/")

    if not args.execute:
        print("\n[DRY-RUN] Keine Dateien wurden verschoben. Mit --execute ausführen.")
    else:
        fuehre_plan_aus(plan, basisordner)
        print(f"\n✓ {len(plan)} Dateien verschoben.")


if __name__ == "__main__":
    main()
