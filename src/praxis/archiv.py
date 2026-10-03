"""Praxisarchiv — durchsuchbarer Index über die historischen Lastenhefte.

Zweck: Zu jedem Kriterium die Textstellen finden, an denen FRÜHERE Kunden
denselben Punkt geregelt haben. Damit lässt sich eine Forderung im neuen
Lastenheft einordnen: Ist sie branchenüblich oder ein Einzelfall?

Abgegrenzt vom Standard: Der Standard (Musterlastenheft) sagt, was gelten
soll — er ist der Maßstab. Das Praxisarchiv sagt, was tatsächlich gefordert
wurde — es ist die Erfahrung. Beides getrennt zu halten ist wesentlich, sonst
wird aus „andere Kunden wollten das auch" ungewollt ein Sollwert.

Der Index liegt als numpy-Array plus JSON auf der Platte und enthält damit
Kundentext im Klartext. Er gehört nicht ins Repository (siehe .gitignore).
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from src.pruefung.kriterien import _lexikalischer_score, ist_verzeichnis
from src.dokumente.pdf_loader import (
    SUPPORTED_SUFFIXES, TextExtraktionsFehler, load_document,
)
from src.dokumente.vector_store import _get_model, normalize_rows
from src.dateien import schreibe_json, speichere_npy
from src.verzeichnisse import DATA_DIR

ARCHIV_DIR  = DATA_DIR / "praxis_index"
EMB_FILE    = "embeddings.npy"
META_FILE   = "metadata.json"
INFO_FILE   = "archiv.json"

# Ein Abschnitt unter dieser Länge trägt keine Aussage (Kopfzeilen, Seitenzahlen).
MIN_ZEICHEN = 120

# Anteil des lexikalischen Scores an der Gesamtbewertung.
#
# Gewählt nach dem Anteil der Treffer aus Dokumenten, die den Punkt laut
# Referenz regeln: Ab diesem Gewicht flacht die Kurve ab, darüber fallen
# Stellen unter die Relevanzschwelle. Das Embedding trägt hier weniger die
# Genauigkeit als die Abdeckung.
LEX_GEWICHT = 0.50

# Relevanzschwelle. Höher als auf der Dokumentseite (0,30) und aus einem
# anderen Grund: Dort ist ein schwacher Kandidat harmlos, das Modell verwirft
# ihn. Hier landet die Stelle ungefiltert vor einem Menschen, der sie für
# einschlägig hält. Ein irreführender Beleg ist schlechter als keiner.
#
# Höhere Schwellen erhöhen die Genauigkeit kaum und lassen mehr Kriterien ohne
# jeden Beleg.
MIN_SCORE = 0.40


@dataclass
class Praxisstelle:
    """Eine Textstelle aus einem historischen Lastenheft."""
    lh_id: str
    seite: int
    text:  str
    score: float = 0.0


@dataclass
class Archivbericht:
    """Ergebnis eines Indexlaufs — auch die Fehlschläge, benannt."""
    dokumente:     list[str] = field(default_factory=list)
    abschnitte:    int = 0
    uebersprungen: list[str] = field(default_factory=list)
    dauer_s:       float = 0.0


def _lh_id(pfad: Path) -> str:
    """Dateiname ohne Endung ist die Dokumentkennung — wie in der Ground Truth."""
    return pfad.stem


def baue_archiv(ordner: Path, ziel: Path | None = None,
                erlaubte_ids: set[str] | None = None,
                progress_callback=None) -> Archivbericht:
    """Liest alle Lastenhefte eines Ordners ein und legt den Index an.

    `erlaubte_ids` beschränkt den Aufbau auf die Dokumente des Korpus. Das ist
    keine Kosmetik: Liegt das Musterlastenheft im selben Ordner, wandert sonst
    der Maßstab ins Erfahrungsarchiv und belegt jede Forderung mit sich selbst.
    Ohne Angabe wird alles aufgenommen, was lesbar ist.

    Dokumente, aus denen kein Text zu gewinnen ist, werden benannt und
    übersprungen — ein stillschweigend fehlendes Dokument wäre später nicht
    von „dieser Punkt wurde nie gefordert" zu unterscheiden.
    """
    ziel = ziel or ARCHIV_DIR
    t0 = time.time()
    bericht = Archivbericht()

    dateien = sorted(p for p in Path(ordner).iterdir()
                     if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES)
    if not dateien:
        raise FileNotFoundError(
            f"In {ordner} liegt kein Lastenheft "
            f"({', '.join(sorted(SUPPORTED_SUFFIXES))})."
        )

    texte: list[str] = []
    meta:  list[dict] = []

    for i, pfad in enumerate(dateien, start=1):
        if progress_callback:
            progress_callback(i, len(dateien), pfad.name)
        if erlaubte_ids is not None and _lh_id(pfad) not in erlaubte_ids:
            bericht.uebersprungen.append(
                f"{pfad.name}: gehört nicht zum Korpus des Musterlastenhefts")
            continue
        try:
            chunks = load_document(pfad, kind="historisch")
        except TextExtraktionsFehler as e:
            bericht.uebersprungen.append(f"{pfad.name}: {e}")
            continue

        lh = _lh_id(pfad)
        # Inhaltsverzeichnisse enthalten jedes Stichwort des Dokuments und
        # gewinnen deshalb jede Stichwortsuche — als Beleg taugen sie nicht.
        # Derselbe Filter wirkt in der Kriterienprüfung auf der Dokumentseite.
        brauchbar = [c for c in chunks
                     if len(c.text.strip()) >= MIN_ZEICHEN
                     and not ist_verzeichnis(c.text)]
        if not brauchbar:
            bericht.uebersprungen.append(
                f"{pfad.name}: kein verwertbarer Abschnitt über {MIN_ZEICHEN} Zeichen")
            continue

        for c in brauchbar:
            texte.append(c.text)
            meta.append({"lh_id": lh, "seite": c.page, "text": c.text})
        bericht.dokumente.append(lh)

    if not texte:
        raise ValueError(f"Aus keinem Dokument in {ordner} war Text zu gewinnen.")

    modell = _get_model()
    emb = modell.encode(texte, batch_size=32,
                        show_progress_bar=False).astype(np.float32)

    # Atomar, und die Kenndaten zuletzt: Bricht der Aufbau ab, bleibt das
    # bisherige Archiv lesbar statt halb überschrieben.
    speichere_npy(ziel / EMB_FILE, emb)
    schreibe_json(ziel / META_FILE, meta, indent=None)

    bericht.abschnitte = len(texte)
    bericht.dauer_s    = time.time() - t0
    schreibe_json(ziel / INFO_FILE, {
        "dokumente":     bericht.dokumente,
        "abschnitte":    bericht.abschnitte,
        "uebersprungen": bericht.uebersprungen,
        "quelle":        str(ordner),
        "erstellt":      time.strftime("%Y-%m-%d %H:%M"),
    })

    return bericht


def archiv_info(ziel: Path | None = None) -> dict | None:
    """Kenndaten des vorhandenen Archivs, oder None wenn keines angelegt ist."""
    p = (ziel or ARCHIV_DIR) / INFO_FILE
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


class Praxisarchiv:
    """Geladener Index über die historischen Lastenhefte.

    Einmal je Prüflauf laden, dann für alle 67 Kriterien wiederverwenden.
    """

    def __init__(self, ziel: Path | None = None):
        d = ziel or ARCHIV_DIR
        emb_p, meta_p = d / EMB_FILE, d / META_FILE
        if not emb_p.exists() or not meta_p.exists():
            raise FileNotFoundError(
                "Kein Praxisarchiv angelegt. Es entsteht aus dem Ordner mit den "
                "historischen Lastenheften — im Reiter „Praxisarchiv“ oder über "
                "`python main.py praxis-index <Ordner>`."
            )
        self.meta: list[dict] = json.loads(meta_p.read_text(encoding="utf-8"))
        self._norm = normalize_rows(np.load(emb_p).astype(np.float32))
        self._klein = [m["text"].lower() for m in self.meta]
        self.dokumente = sorted({m["lh_id"] for m in self.meta})

    def __len__(self) -> int:
        return len(self.meta)

    def suche(self, query_vec: np.ndarray, begriffe: list[str] | None = None,
              n: int = 4, min_score: float = MIN_SCORE,
              lexikalisches_gewicht: float = LEX_GEWICHT,
              max_je_dokument: int = 1,
              nur_dokument: str | None = None) -> list[Praxisstelle]:
        """Passendste Stellen, hybrid bewertet, über Dokumente gestreut.

        `max_je_dokument` erzwingt Streuung: Vier Treffer aus demselben
        Lastenheft belegen nur, dass dieses eine Dokument den Punkt ausführlich
        regelt. Vier Treffer aus vier Dokumenten belegen, dass mehrere Kunden
        ihn regeln — und das ist die Frage, die dieser Index beantworten soll.

        `nur_dokument` kehrt das um und sucht in genau einem Lastenheft. Nötig
        für den Vergleich gegen ein einzelnes, gezielt ausgewähltes Dokument;
        `max_je_dokument` ist dann sinnvollerweise auf `n` zu setzen.
        """
        if not self.meta:
            return []
        q = query_vec / (np.linalg.norm(query_vec) + 1e-10)
        scores = self._norm @ q

        if begriffe and lexikalisches_gewicht > 0:
            lex = np.array([_lexikalischer_score(t, begriffe) for t in self._klein],
                           dtype=np.float32)
            scores = (1 - lexikalisches_gewicht) * scores + lexikalisches_gewicht * lex

        je_dok: dict[str, int] = {}
        treffer: list[Praxisstelle] = []
        for i in np.argsort(scores)[::-1]:
            if len(treffer) >= n:
                break
            wert = float(scores[i])
            if wert < min_score:
                break                      # absteigend sortiert
            m = self.meta[i]
            if nur_dokument and m["lh_id"] != nur_dokument:
                continue
            if je_dok.get(m["lh_id"], 0) >= max_je_dokument:
                continue
            je_dok[m["lh_id"]] = je_dok.get(m["lh_id"], 0) + 1
            treffer.append(Praxisstelle(m["lh_id"], m["seite"], m["text"], wert))
        return treffer
