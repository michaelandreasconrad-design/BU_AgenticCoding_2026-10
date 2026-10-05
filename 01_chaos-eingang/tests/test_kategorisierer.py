import pytest
from pathlib import Path
import tempfile
import os
from unittest.mock import patch, MagicMock

# Damit der Import funktioniert, muss kategorisierer.py im Elternordner liegen
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from kategorisierer import lade_datei_inventar, IGNORIERTE_DATEIEN, klassifiziere_mit_claude, GUELTIGE_KATEGORIEN


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


def test_klassifikation_fehlt_datei_wird_sonstiges():
    # Claude gibt nicht alle Dateien zurück -> fehlende bekommen "Sonstiges"
    inventar = [
        {"name": "rechnung.txt", "extension": ".txt", "content_preview": "Amazon Rechnung"},
        {"name": "foto.jpg", "extension": ".jpg", "content_preview": ""},
        {"name": "memo.txt", "extension": ".txt", "content_preview": "Erinnerung"},
    ]
    # Claude gibt nur 2 von 3 Dateien zurück
    antwort_json = '{"rechnung.txt": "Rechnungen", "foto.jpg": "Fotos"}'
    mock_response = MagicMock()
    mock_response.content[0].text = antwort_json

    with patch("kategorisierer.anthropic.Anthropic") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create.return_value = mock_response

        ergebnis = klassifiziere_mit_claude(inventar)

    # Alle 3 Dateien sollten in Ergebnis sein
    assert ergebnis["rechnung.txt"] == "Rechnungen"
    assert ergebnis["foto.jpg"] == "Fotos"
    # Fehlende Datei sollte auf "Sonstiges" fallen
    assert ergebnis["memo.txt"] == "Sonstiges"
    assert len(ergebnis) == 3
