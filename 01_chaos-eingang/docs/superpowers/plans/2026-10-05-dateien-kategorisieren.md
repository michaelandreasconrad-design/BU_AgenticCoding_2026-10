# Datei-Kategorisierer Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Ziel:** Ein Python-Skript, das Dateien in einem Chaos-Ordner per Claude-API inhaltlich analysiert und automatisch in thematische Unterordner einsortiert.

**Architektur:** Das Skript liest alle Dateien im Zielordner, extrahiert für Textdateien den Inhalt und für Binärdateien Dateiname und Endung, sendet diese Infos in einer einzigen Claude-Anfrage zur Batch-Klassifikation und verschiebt die Dateien anschließend in die Zielordner. Duplikate (byte-identisch per MD5) landen in einem eigenen Unterordner. Ein `--dry-run`-Modus (Standard) zeigt das Ergebnis ohne Datei-Änderungen.

**Tech Stack:** Python 3.10+, Anthropic SDK (`anthropic`), Standardbibliothek (`pathlib`, `shutil`, `hashlib`, `json`, `argparse`)

**Spec:** Diese Datei ist die Spec.

## Global Constraints

- Python 3.10+
- Einzige externe Abhängigkeit: `anthropic` (per pip installieren)
- Modell: `claude-opus-5-5`
- `QUELLEN_echte-daten.md` wird explizit ignoriert (Kursunterlage, kein Sortierobjekt)
- Dry-run ist der **Standard**; tatsächliches Verschieben nur mit `--execute`
- Zielkategorien: `Rechnungen`, `Briefe`, `Vertraege`, `Notizen`, `Fotos`, `Screenshots`, `Daten`, `Duplikate`, `Sonstiges`
- Dateinamen mit Sonderzeichen und Leerzeichen müssen funktionieren
- Dateien nicht stillschweigend überschreiben, wenn Zieldatei schon existiert

## Review Focus

- Textdatei mit encoding-Fehler (Latin-1 statt UTF-8) → Skript darf nicht abstürzen; Fallback `errors="replace"` nötig — Task 1, Schritt „Text lesen"
- Datei mit Leerzeichen im Namen (`foto - Kopie.jpg`) → `shutil.move` mit `pathlib.Path`-Objekten aufrufen, nicht mit rohen Strings — Task 3, Schritt „Datei verschieben"
- Claude gibt unbekannte Kategorie zurück → Fallback auf `Sonstiges` — Task 2, JSON-Parsing
- Zieldatei existiert bereits (gleichnamige Datei in Zielkategorie) → Zieldateiname mit `_2`, `_3` … nummerieren statt Überschreiben — Task 3
- Claude-API-Key nicht gesetzt → klare Fehlermeldung, kein Traceback — Task 2, Client-Initialisierung

---

## Dateistruktur

```
01_chaos-eingang/
├── kategorisierer.py        ← Hauptskript (erstellen)
├── tests/
│   └── test_kategorisierer.py  ← Tests (erstellen)
└── docs/superpowers/plans/
    └── 2026-10-05-dateien-kategorisieren.md
```

---

### Task 1: Datei-Inventar aufbauen

**Dateien:**
- Erstellen: `kategorisierer.py`
- Erstellen: `tests/test_kategorisierer.py`

**Interfaces:**
- Produziert: `list[dict]` — eine Liste von Datei-Einträgen, jeder mit den Schlüsseln `path` (Path), `name` (str), `extension` (str), `content_preview` (str, leer für Binärdateien), `md5` (str)

---

- [ ] **Schritt 1: Failing Test schreiben**

Datei `tests/test_kategorisierer.py` anlegen:

```python
import pytest
from pathlib import Path
import tempfile
import os

# Damit der Import funktioniert, muss kategorisierer.py im Elternordner liegen
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from kategorisierer import lade_datei_inventar, IGNORIERTE_DATEIEN


def test_inventar_liest_textdatei(tmp_path):
    (tmp_path / "rechnung.txt").write_text("Musterrechnung Inhalt", encoding="utf-8")
    inventar = lade_datei_inventar(tmp_path)
    assert len(inventar) == 1
    eintrag = inventar[0]
    assert eintrag["name"] == "rechnung.txt"
    assert eintrag["extension"] == ".txt"
    assert "Musterrechnung" in eintrag["content_preview"]
    assert len(eintrag["md5"]) == 32


def test_inventar_ignoriert_kursunterlage(tmp_path):
    (tmp_path / "QUELLEN_echte-daten.md").write_text("Kursinhalt", encoding="utf-8")
    (tmp_path / "normal.txt").write_text("Normal", encoding="utf-8")
    inventar = lade_datei_inventar(tmp_path)
    namen = [e["name"] for e in inventar]
    assert "QUELLEN_echte-daten.md" not in namen
    assert "normal.txt" in namen


def test_inventar_liest_binaerdatei(tmp_path):
    (tmp_path / "foto.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)
    inventar = lade_datei_inventar(tmp_path)
    assert len(inventar) == 1
    assert inventar[0]["content_preview"] == ""
    assert inventar[0]["extension"] == ".jpg"


def test_inventar_toleriert_encoding_fehler(tmp_path):
    (tmp_path / "latin.txt").write_bytes(b"Stra\xdfe")  # ß in Latin-1
    inventar = lade_datei_inventar(tmp_path)
    assert len(inventar) == 1
    assert "content_preview" in inventar[0]
```

- [ ] **Schritt 2: Test scheitern lassen**

```
cd 01_chaos-eingang
python -m pytest tests/test_kategorisierer.py -v
```

Erwartet: `ModuleNotFoundError: No module named 'kategorisierer'`

- [ ] **Schritt 3: Minimale Implementierung schreiben**

Datei `kategorisierer.py` anlegen:

```python
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
```

- [ ] **Schritt 4: Tests grün machen**

```
python -m pytest tests/test_kategorisierer.py -v
```

Erwartet: 4 × PASSED

- [ ] **Schritt 5: Commit**

```
git add kategorisierer.py tests/test_kategorisierer.py
git commit -m "feat: Datei-Inventar einlesen mit MD5 und Encoding-Toleranz

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Claude-Klassifikation

**Dateien:**
- Modifizieren: `kategorisierer.py`
- Modifizieren: `tests/test_kategorisierer.py`

**Interfaces:**
- Konsumiert: `list[dict]` aus Task 1
- Produziert: `dict[str, str]` — Mapping `Dateiname → Kategorie`; gültige Kategorien: `Rechnungen`, `Briefe`, `Vertraege`, `Notizen`, `Fotos`, `Screenshots`, `Daten`, `Duplikate`, `Sonstiges`

---

- [ ] **Schritt 1: Failing Tests schreiben**

In `tests/test_kategorisierer.py` ergänzen:

```python
from unittest.mock import patch, MagicMock
from kategorisierer import klassifiziere_mit_claude, GUELTIGE_KATEGORIEN


def test_klassifikation_parst_json():
    inventar = [
        {"name": "rechnung.txt", "extension": ".txt", "content_preview": "Amazon Rechnung"},
        {"name": "foto.jpg", "extension": ".jpg", "content_preview": ""},
    ]
    antwort_json = '{"rechnung.txt": "Rechnungen", "foto.jpg": "Fotos"}'
    mock_response = MagicMock()
    mock_response.content[0].text = antwort_json

    with patch("kategorisierer.anthropic.Anthropic") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create.return_value = mock_response

        ergebnis = klassifiziere_mit_claude(inventar)

    assert ergebnis["rechnung.txt"] == "Rechnungen"
    assert ergebnis["foto.jpg"] == "Fotos"


def test_klassifikation_faellt_auf_sonstiges_zurueck():
    inventar = [{"name": "kryptisch.xyz", "extension": ".xyz", "content_preview": ""}]
    antwort_json = '{"kryptisch.xyz": "UnbekannteKategorie"}'
    mock_response = MagicMock()
    mock_response.content[0].text = antwort_json

    with patch("kategorisierer.anthropic.Anthropic") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create.return_value = mock_response

        ergebnis = klassifiziere_mit_claude(inventar)

    assert ergebnis["kryptisch.xyz"] == "Sonstiges"
```

- [ ] **Schritt 2: Test scheitern lassen**

```
python -m pytest tests/test_kategorisierer.py::test_klassifikation_parst_json -v
```

Erwartet: `ImportError: cannot import name 'klassifiziere_mit_claude'`

- [ ] **Schritt 3: Implementierung in `kategorisierer.py` ergänzen**

Oben einfügen:

```python
import json
import os
import anthropic
```

Konstante und Funktion ergänzen:

```python
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

    # Ungültige Kategorien auf Sonstiges normieren
    return {
        name: (kat if kat in GUELTIGE_KATEGORIEN else "Sonstiges")
        for name, kat in mapping.items()
    }
```

- [ ] **Schritt 4: Tests grün machen**

```
python -m pytest tests/test_kategorisierer.py -v
```

Erwartet: 6 × PASSED

- [ ] **Schritt 5: Commit**

```
git add kategorisierer.py tests/test_kategorisierer.py
git commit -m "feat: Claude-Klassifikation mit Fallback auf Sonstiges

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Duplikat-Erkennung und Dateiverschiebung

**Dateien:**
- Modifizieren: `kategorisierer.py`
- Modifizieren: `tests/test_kategorisierer.py`

**Interfaces:**
- Konsumiert: `list[dict]` aus Task 1, `dict[str, str]` aus Task 2
- Produziert: `list[dict]` — Aktionsprotokoll mit `{"von": str, "nach": str, "aktion": "verschieben"|"duplikat"|"konflikt"}`

---

- [ ] **Schritt 1: Failing Tests schreiben**

In `tests/test_kategorisierer.py` ergänzen:

```python
from kategorisierer import finde_duplikate, plane_verschiebungen


def test_duplikat_erkennung():
    inventar = [
        {"name": "foto.jpg", "md5": "abc123", "path": Path("/tmp/foto.jpg")},
        {"name": "foto - Kopie.jpg", "md5": "abc123", "path": Path("/tmp/foto - Kopie.jpg")},
        {"name": "rechnung.txt", "md5": "def456", "path": Path("/tmp/rechnung.txt")},
    ]
    duplikate = finde_duplikate(inventar)
    assert "foto - Kopie.jpg" in duplikate or "foto.jpg" in duplikate
    assert "rechnung.txt" not in duplikate


def test_verschiebungsplan_respektiert_duplikate(tmp_path):
    inventar = [
        {"name": "foto.jpg", "md5": "abc123", "path": tmp_path / "foto.jpg", "extension": ".jpg"},
        {"name": "kopie.jpg", "md5": "abc123", "path": tmp_path / "kopie.jpg", "extension": ".jpg"},
    ]
    mapping = {"foto.jpg": "Fotos", "kopie.jpg": "Fotos"}
    duplikate = {"kopie.jpg"}
    plan = plane_verschiebungen(inventar, mapping, duplikate, tmp_path)

    aktionen = {a["von"]: a["aktion"] for a in plan}
    assert aktionen["foto.jpg"] == "verschieben"
    assert aktionen["kopie.jpg"] == "duplikat"


def test_verschiebungsplan_vermeidet_ueberschreiben(tmp_path):
    (tmp_path / "Rechnungen").mkdir()
    (tmp_path / "Rechnungen" / "rechnung.txt").write_text("alt")

    inventar = [
        {"name": "rechnung.txt", "md5": "neu123", "path": tmp_path / "rechnung.txt", "extension": ".txt"},
    ]
    mapping = {"rechnung.txt": "Rechnungen"}
    plan = plane_verschiebungen(inventar, mapping, set(), tmp_path)

    assert plan[0]["nach"].endswith("rechnung_2.txt") or "_2" in plan[0]["nach"]
```

- [ ] **Schritt 2: Test scheitern lassen**

```
python -m pytest tests/test_kategorisierer.py::test_duplikat_erkennung -v
```

Erwartet: `ImportError: cannot import name 'finde_duplikate'`

- [ ] **Schritt 3: Implementierung ergänzen**

In `kategorisierer.py` ergänzen:

```python
import shutil


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
```

- [ ] **Schritt 4: Tests grün machen**

```
python -m pytest tests/test_kategorisierer.py -v
```

Erwartet: 9 × PASSED

- [ ] **Schritt 5: Commit**

```
git add kategorisierer.py tests/test_kategorisierer.py
git commit -m "feat: Duplikat-Erkennung und Dateiverschiebung mit Konflikt-Schutz

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Hauptprogramm und Bericht

**Dateien:**
- Modifizieren: `kategorisierer.py`

**Interfaces:**
- Konsumiert: alle bisherigen Funktionen
- Produziert: CLI-Programm mit `--execute`-Flag und Konsolenausgabe des Plans

---

- [ ] **Schritt 1: Failing Test schreiben**

In `tests/test_kategorisierer.py` ergänzen:

```python
import subprocess
import sys


def test_dry_run_aendert_keine_dateien(tmp_path):
    (tmp_path / "rechnung.txt").write_text("Amazon Rechnung 12,99 EUR", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "kategorisierer.py", str(tmp_path)],
        capture_output=True, text=True, cwd=Path(__file__).parent.parent
    )
    # Dry-run: Datei muss noch an Originalposition liegen
    assert (tmp_path / "rechnung.txt").exists(), "Dry-run darf keine Dateien verschieben"
    assert result.returncode == 0
```

Hinweis: Dieser Test ruft die echte Claude-API auf. Er schlägt fehl, wenn `ANTHROPIC_API_KEY` nicht gesetzt ist — das ist gewollt.

- [ ] **Schritt 2: Test scheitern lassen**

```
python -m pytest tests/test_kategorisierer.py::test_dry_run_aendert_keine_dateien -v
```

Erwartet: Fehler (API-Key nicht gesetzt oder fehlende `main`-Funktion)

- [ ] **Schritt 3: main() und CLI ergänzen**

Ans Ende von `kategorisierer.py` anfügen:

```python
import argparse
import sys


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
```

- [ ] **Schritt 4: Manuell testen (Dry-Run)**

```
python kategorisierer.py . --dry-run
```

Erwartet: Liste der geplanten Verschiebungen ohne tatsächliche Änderungen.

- [ ] **Schritt 5: Finale Tests grün machen**

```
python -m pytest tests/test_kategorisierer.py -v -k "not dry_run"
```

(Der `dry_run`-Test nur mit echtem API-Key ausführen)

- [ ] **Schritt 6: Abschluss-Commit**

```
git add kategorisierer.py
git commit -m "feat: CLI mit Dry-run-Standard und Konsolenausgabe

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Bekannte Stolpersteine im Chaos-Ordner

| Datei | Kategorie | Anmerkung |
|---|---|---|
| `handwerker.txt` | Rechnungen | Name irreführend — Inhalt ist eine Sanitär-Rechnung |
| `final_FINAL_v2.txt` | Briefe | Chaotischer Name — Inhalt ist Krankenkassenantrag |
| `Unbenannt.txt` | Vertraege | Kein Name — Inhalt ist Mietvertrag-Nachtrag |
| `dokument (1).txt` | Rechnungen | Klammern im Namen — Telekom-Rechnung |
| `foto - Kopie.jpg` | Duplikate | Byte-identisch mit `foto.jpg` |
| `QUELLEN_echte-daten.md` | — | Kursunterlage, wird ignoriert |
