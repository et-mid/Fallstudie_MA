"""Das Einbettungsmodell und die Normalisierung — mehr braucht es nicht.

Der Name ist historisch: Hier lag einmal ein vollständiger Vektorspeicher mit
Indexdatei, Suche und Dokumentbewertung. Davon ist nichts übrig geblieben, weil
jeder Nutzer inzwischen seinen eigenen, passenden Index mitbringt:

- `src/praxis/archiv.py` hält den Index über die historischen Lastenhefte
- `standard_suche.py` einen über die Einzelaussagen des Standards
- `kriterien.py` bettet das geprüfte Lastenheft je Lauf frisch ein

Geblieben sind die beiden Dinge, die sie sich teilen: dasselbe Modell — sonst
wären die Vektoren nicht vergleichbar — und dieselbe Normalisierung.
"""

import hashlib

import numpy as np
from sentence_transformers import SentenceTransformer

from src.verzeichnisse import DATA_DIR

_model: SentenceTransformer | None = None

MODELL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# Zwischenspeicher für Einbettungen, im Prozess und auf der Platte. Der
# Schlüssel ist der Inhalt: Modellname plus die Texte selbst. Damit braucht
# keine Aufrufstelle einen Fingerabdruck zu führen, und ein geänderter Standard
# bekommt von selbst neue Vektoren.
#
# Anlass: Die Einbettung der Standardaussagen und Kriterienabfragen ist bei jedem
# Dokument gleich und kostete bei jedem Lauf spürbar Zeit.
VEKTOREN_DIR = DATA_DIR / "vektoren"
_zwischenspeicher: dict[str, np.ndarray] = {}


def _schluessel(texte: list[str]) -> str:
    h = hashlib.sha1(MODELL_NAME.encode("utf-8"))
    for t in texte:
        h.update(b"\x1f")
        h.update(t.encode("utf-8"))
    return h.hexdigest()


def einbetten(texte: list[str], zwischenspeichern: bool = True) -> np.ndarray:
    """Einbettungen der Texte, float32, unnormiert.

    `zwischenspeichern=False` rechnet immer neu — für Messungen, die den
    Speicher ausdrücklich umgehen sollen.
    """
    if not texte:
        return np.zeros((0, 0), dtype=np.float32)
    if not zwischenspeichern:
        return _get_model().encode(texte, batch_size=32,
                                   show_progress_bar=False).astype(np.float32)

    k = _schluessel(texte)
    v = _zwischenspeicher.get(k)
    if v is not None:
        return v
    datei = VEKTOREN_DIR / f"{k}.npy"
    if datei.exists():
        try:
            v = np.load(datei)
            if v.shape[0] == len(texte):
                _zwischenspeicher[k] = v
                return v
        except (OSError, ValueError):
            pass          # beschädigte Datei: neu rechnen und überschreiben
    v = _get_model().encode(texte, batch_size=32,
                            show_progress_bar=False).astype(np.float32)
    _zwischenspeicher[k] = v
    try:
        VEKTOREN_DIR.mkdir(parents=True, exist_ok=True)
        np.save(datei, v)
    except OSError:
        pass              # ein nicht beschreibbarer Speicher darf den Lauf nicht verhindern
    return v


def _get_model() -> SentenceTransformer:
    """Das Einbettungsmodell, einmal geladen und dann wiederverwendet.

    Mehrsprachig, weil ein Teil der Lastenhefte englisch ist. Klein genug, um
    auf einem Arbeitsplatzrechner ohne Grafikkarte zu laufen — das Briefing
    verlangt, dass alles lokal bleibt.
    """
    global _model
    if _model is None:
        _model = SentenceTransformer(MODELL_NAME)
    return _model


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    """Zeilenweise L2-Normalisierung. Einmal vorab, dann wiederverwenden.

    Danach ist das Skalarprodukt zweier Zeilen ihre Kosinus-Ähnlichkeit — die
    teure Division entfällt bei jeder einzelnen Suche.
    """
    return matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10)
