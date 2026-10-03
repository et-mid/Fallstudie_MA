"""Wo die Software ihre Dateien findet — an einer Stelle statt in jedem Modul.

Vorher rechnete jedes Modul seinen Datenordner aus der eigenen Lage aus
(`Path(__file__).parent.parent / "data"`). Das stimmte nur, solange alle Module
in derselben Tiefe lagen.

Die Gliederungsdatei hieß früher `struktur_67_kriterien.json`. Die Zahl wechselt
aber mit jedem Musterlastenheft. Eine Datei unter dem alten Namen wird beim
ersten Import umbenannt, im Datenordner wie in jedem Eintrag der Bibliothek.
"""

from pathlib import Path

BASIS      = Path(__file__).resolve().parent.parent
DATA_DIR   = BASIS / "data"
DEMO_DIR   = BASIS / "demo"
OUTPUT_DIR = BASIS / "output"

STRUKTUR_NAME = "struktur_kriterien.json"

# Referenzbewertungen für Auswertung und Training des Entscheiders. Die aktive
# Datei steht in GT_ABGLEICH und GT_TESTFAELLE; ältere Dateien bleiben zur
# Nachrechnung früherer Läufe.
GT_ABGLEICH      = DATA_DIR / "Ground_Truth_Lastenheft_Abgleich_v1.5.json"
GT_TESTFAELLE    = DATA_DIR / "Ground_Truth_Testfaelle_v1.5.jsonl"
GT_ABGLEICH_1_4  = DATA_DIR / "Ground_Truth_Lastenheft_Abgleich_v1.4.json"
GT_TESTFAELLE_1_4 = DATA_DIR / "Ground_Truth_Testfaelle_v1.4.jsonl"
GT_ABGLEICH_1_3  = DATA_DIR / "Ground_Truth_Lastenheft_Abgleich_v1.3.json"
GT_TESTFAELLE_1_3 = DATA_DIR / "Ground_Truth_Testfaelle_v1.3.jsonl"
GT_ABGLEICH_1_2  = DATA_DIR / "Ground_Truth_Lastenheft_Abgleich_v1.2.json"
GT_TESTFAELLE_1_2 = DATA_DIR / "Ground_Truth_Testfaelle_v1.2.jsonl"
GT_ABGLEICH_1_1  = DATA_DIR / "Ground_Truth_Lastenheft_Abgleich_v1.1.json"
GT_TESTFAELLE_1_1 = DATA_DIR / "Ground_Truth_Testfaelle_v1.1.jsonl"
GT_ABGLEICH_1_0  = DATA_DIR / "Ground_Truth_Lastenheft_Abgleich.json"
GT_TESTFAELLE_1_0 = DATA_DIR / "Ground_Truth_Testfaelle.jsonl"
_STRUKTUR_ALT = "struktur_67_kriterien.json"


def _alte_namen_umstellen() -> None:
    ordner = [DATA_DIR, *(sorted((DATA_DIR / "standards").iterdir())
                          if (DATA_DIR / "standards").is_dir() else [])]
    for o in ordner:
        alt, neu = o / _STRUKTUR_ALT, o / STRUKTUR_NAME
        try:
            if alt.is_file() and not neu.exists():
                alt.rename(neu)
        except OSError:
            pass      # schreibgeschützt o. Ä. — dann fehlt die Datei sichtbar


_alte_namen_umstellen()
