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
