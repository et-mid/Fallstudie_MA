"""Ein neues Musterlastenheft aus hochgeladenen Kundenlastenheften erzeugen.

Das bestehende Druckguss-Musterlastenheft ist von Hand aus 18 Lastenheften
zusammengetragen worden. Für ein anderes Anwendungsfeld gibt es diesen Standard
nicht — und ohne ihn kann die Prüfung nur feststellen, OB ein Punkt geregelt ist.
Dieses Modul erzeugt einen **Entwurf** im selben Format, den der Fachbereich in
Word überarbeitet und dann wie gewohnt übernimmt.

## Drei Phasen, jede mit Zwischenstand auf der Platte

1. **Gliederung vorschlagen** — Kapitelüberschriften aus allen Lastenheften
   ziehen, gleichartige Themen über die Dokumente hinweg zusammenfassen,
   Kriterien und Kapitel benennen. **Jedes Thema kommt in die Gliederung**, auch
   wenn es nur ein Lastenheft behandelt — wie oft es vorkommt, steht danach in
   der Einstufung (Pflicht / Regel / Optional), nicht in der Auswahl. Deshalb
   genügt auch ein einziges Lastenheft.
2. **Gliederung prüfen** — in der Oberfläche; umbenennen, streichen, ergänzen.
   Die Gliederung ist das, was später jede Prüfung trägt. Sie ungesehen aus
   einer Häufung von Überschriften zu übernehmen, wäre der falsche Ort zum
   Sparen.
3. **Inhalte erzeugen** — je Kriterium die passenden Stellen der Lastenhefte
   sammeln, das Modell Standardanforderungen, Ausprägungen, Platzhalter und
   Abgleichbegriffe formulieren lassen, die Antwort gegen die Stellen prüfen,
   Word-Datei schreiben.

Alles läuft lokal. Phase 3 ist ein Aufruf je Kriterium mit langem Prompt, rund
eine Minute auf dem Entwicklungsrechner; bei 70 Kriterien gut eine Stunde.
Deshalb wird nach jedem Kriterium gesichert, die Abschnittsvektoren liegen im
Arbeitsordner, und ein erneuter Start setzt dort auf.

## Was ein Entwurf nicht ist

**Die Belegzahlen sind eine grobe Schätzung.** Ein Lastenheft gilt als
belegend, wenn es eine eigene Überschrift zum Thema hat oder eine ähnliche
Stelle. Ähnlichkeit trennt „regelt“ kaum von „regelt nicht“; die Einstufung
Pflicht / Regel / Optional ist entsprechend ungenau (siehe AEHNLICH_BELEG).

**Die Standardanforderungen sind Modelltext.** Ausprägungen werden gegen die
Stelle genau des Lastenhefts geprüft, das sie nennen, Abgleichbegriffe gegen
die Quellstellen. Die Anforderungen lassen sich so nicht prüfen: Sie sollen
zusammenfassen statt zitieren.
"""

from __future__ import annotations

import json
import os
import re
import signal
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from src.muster import musterdocx
from src.verzeichnisse import DATA_DIR as _DATA_DIR

DATA_DIR = _DATA_DIR
ARBEITSORDNER = DATA_DIR / "musteraufbau"

MODELL = "qwen3.5:9b"

# Ab dieser Kosinus-Ähnlichkeit gelten zwei Überschriften als dasselbe Thema —
# und zwar JEDES Paar einer Gruppe (vollständige Verknüpfung). Mittlere
# Verknüpfung verkettete kurze Überschriften über Zwischenglieder zu
# zusammengewürfelten Gruppen. Eine überzählige Zeile streicht man in der
# Prüfung leichter als einen vermischten Inhalt.
AEHNLICH_UEBERSCHRIFT = 0.65
VERKNUEPFUNG = "complete"
# Themen, die weniger Lastenhefte als diese Zahl eigens behandeln, fallen weg.
#
# Vorgabe 1: Alle Themen aller Lastenhefte kommen in die Gliederung. Die
# Häufigkeit entscheidet über die Einstufung, nicht über die Aufnahme — ein
# Thema aus nur einem Lastenheft wird „Optional“, nicht gestrichen. Damit
# funktioniert der Aufbau auch mit einem einzigen Lastenheft.
MIN_BELEGE = 1

# Ab so viel eigenem Text zählt ein Kapitel mit Unterkapiteln selbst als Thema.
# Eine Zeile wie „Die folgenden Abschnitte regeln die Technik." bleibt darunter.
MIN_EIGENER_TEXT = 80

# Überschriften, die kein Thema benennen, sondern ein Dokumentteil.
GENERISCH = {"allgemein", "allgemeines", "anhang", "anhänge", "anlage", "anlagen",
             "sonstiges", "sonstige", "inhalt", "inhaltsverzeichnis", "bemerkung",
             "bemerkungen", "hinweis", "hinweise", "tabelle", "abbildung", "general",
             "annex", "appendix", "others", "remarks", "vorwort", "einleitung",
             "introduction", "änderungen", "änderungsindex", "verteiler"}
# Ab dieser Ähnlichkeit zählt eine Stelle ohne eigene Überschrift als Beleg.
#
# Abgestimmt an Referenzbewertungen: Ähnlichkeit trennt „regelt“ kaum von
# „regelt nicht“. Die Schwelle kommt der durchschnittlichen Belegzahl des von
# Hand erstellten Musterlastenhefts am nächsten; die Einstufung bleibt eine
# grobe Schätzung und ist so gekennzeichnet.
AEHNLICH_BELEG = 0.55

SUFFIXE = (".pdf", ".docx")


# ── Arbeitsordner ─────────────────────────────────────────────────────────────

# Lebenszeichen des Hintergrundlaufs: alle PULS_TAKT Sekunden, unabhängig vom
# Fortschritt — auch während eine lange Texterkennung keinen Schritt meldet.
# Bleibt es länger als PULS_GRENZE aus, ist der Prozess beendet. Bis zum ersten
# Lebenszeichen darf der Start ANLAUF Sekunden dauern (Python lädt vorher torch).
PULS_TAKT = 5
PULS_GRENZE = 60
ANLAUF = 180


@dataclass
class Arbeitsstand:
    ordner: Path = ARBEITSORDNER
    # Prozessnummer des Laufs, der hier schreibt. Nur der Hintergrundlauf setzt
    # sie; die Oberfläche meldet den Start ohne, damit nicht ihr eigener Prozess
    # als Lauf gilt und beim Abbrechen beendet wird.
    pid: int | None = None

    @property
    def dokumente(self) -> Path:
        return self.ordner / "dokumente"

    @property
    def gliederung(self) -> Path:
        return self.ordner / "gliederung.json"

    @property
    def inhalte(self) -> Path:
        return self.ordner / "inhalte.json"

    @property
    def fortschritt(self) -> Path:
        return self.ordner / "fortschritt.json"

    @property
    def protokoll(self) -> Path:
        return self.ordner / "protokoll.txt"

    @property
    def puls(self) -> Path:
        return self.ordner / "puls.txt"

    def entwurf(self, gegenstand: str) -> Path:
        name = re.sub(r"[^\wÄÖÜäöüß-]+", "_", gegenstand).strip("_") or "Entwurf"
        return self.ordner / f"Standard-Lastenheft_{name}_Entwurf.docx"

    def dateien(self) -> list[Path]:
        if not self.dokumente.exists():
            return []
        return sorted(p for p in self.dokumente.iterdir()
                      if p.is_file() and p.suffix.lower() in SUFFIXE)

    def lesen(self, pfad: Path, vorgabe=None):
        try:
            return json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return vorgabe

    def schreiben(self, pfad: Path, daten) -> None:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        tmp = pfad.with_suffix(pfad.suffix + ".tmp")
        tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(pfad)          # nie eine halb geschriebene Datei lesen

    def melden(self, phase: str, schritt: int, gesamt: int, text: str,
               fertig: bool = False, fehler: str | None = None) -> None:
        self.schreiben(self.fortschritt, {
            "phase": phase, "schritt": schritt, "gesamt": gesamt, "text": text,
            "fertig": fertig, "fehler": fehler, "pid": self.pid,
            "aktualisiert": time.time(),
        })


@contextmanager
def lebenszeichen(stand: Arbeitsstand):
    """Hält den Lauf als lebend sichtbar und trägt seine Prozessnummer ein."""
    stand.pid = os.getpid()
    halt = threading.Event()

    def pulsschlag():
        while not halt.is_set():
            try:
                stand.puls.parent.mkdir(parents=True, exist_ok=True)
                stand.puls.write_text(str(time.time()), encoding="utf-8")
            except OSError:
                pass
            halt.wait(PULS_TAKT)

    faden = threading.Thread(target=pulsschlag, daemon=True)
    faden.start()
    try:
        yield
    finally:
        halt.set()


def laeuft(stand: Arbeitsstand) -> bool:
    """Ob gerade ein Aufbau läuft — am Lebenszeichen des Prozesses erkannt,
    nicht am Fortschritt. Ein Schritt darf beliebig lange dauern."""
    f = stand.lesen(stand.fortschritt)
    if not f or f.get("fertig") or f.get("fehler"):
        return False
    try:
        puls = float(stand.puls.read_text(encoding="utf-8"))
        return time.time() - puls < PULS_GRENZE
    except (OSError, ValueError):
        # Noch kein Lebenszeichen: Der Prozess startet gerade.
        return time.time() - float(f.get("aktualisiert") or 0) < ANLAUF


ABGEBROCHEN = "Vom Nutzer abgebrochen."


def abbrechen(stand: Arbeitsstand) -> None:
    """Beendet einen laufenden Aufbau und vermerkt den Abbruch. Gesichertes
    bleibt erhalten; ein neuer Start setzt darauf auf."""
    f = stand.lesen(stand.fortschritt) or {}
    pid = f.get("pid")
    if laeuft(stand) and pid and int(pid) != os.getpid():
        try:
            os.kill(int(pid), signal.SIGTERM)    # unter Windows: TerminateProcess
        except OSError:
            pass
    stand.pid = None
    stand.melden(f.get("phase") or "vorschlag", 0, 1, "Abgebrochen",
                 fehler=ABGEBROCHEN)
    try:
        stand.puls.unlink()
    except OSError:
        pass


def entfernen(stand: Arbeitsstand, name: str) -> bool:
    """Löscht ein hochgeladenes Lastenheft aus dem Arbeitsordner. Nur Dateien
    direkt in `dokumente/`, keine Pfade."""
    pfad = stand.dokumente / Path(name).name
    if pfad.parent != stand.dokumente or not pfad.is_file():
        return False
    pfad.unlink()
    return True


# ── Dokumente lesen ───────────────────────────────────────────────────────────

@dataclass
class Ueberschrift:
    nr: str
    titel: str
    seite: int
    position: float = 0.0          # 0 = Dokumentanfang, 1 = Ende
    container: bool = False        # hat Unterüberschriften
    eltern: str = ""
    eigener_text: int = 0          # Zeichen zwischen dieser und der nächsten Überschrift


@dataclass
class Quelle:
    kennung: str
    pfad: Path
    seiten: list[str]
    chunks: list = field(default_factory=list)
    ueberschriften: list[Ueberschrift] = field(default_factory=list)


def seiten_laden(pfad: Path) -> list[str]:
    """Seitentext über denselben Zwischenspeicher wie die Prüfung — kein zweites OCR."""
    from src.dokumente.pdf_loader import _cache_lesen, _cache_schreiben, _docx_pages, _seiten_lesen

    if pfad.suffix.lower() == ".docx":
        return _docx_pages(pfad)
    gespeichert = _cache_lesen(pfad)
    if gespeichert is not None:
        return gespeichert[0]
    seiten, gesamt, ohne = _seiten_lesen(pfad)
    _cache_schreiben(pfad, seiten, gesamt, ohne)
    return seiten


_KOPF   = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+([A-ZÄÖÜ][^\n]{2,80}?)\s*:?\s*$")
_TOC    = re.compile(r"\.{4,}|…{2,}|\s\d{1,3}\s*$")
_DATUM  = re.compile(r"\b(januar|februar|märz|april|mai|juni|juli|august|september|oktober"
                     r"|november|dezember|january|february|march|may|june|july|october"
                     r"|december)\b.*\b(19|20)\d\d\b", re.I)


def ueberschriften(seiten: list[str]) -> list[Ueberschrift]:
    """Nummerierte Kapitelüberschriften aus dem Seitentext.

    Die Treffer enthalten Rauschen — englische Doppelungen, Datumszeilen,
    nummerierte Listenpunkte, OCR-Reste. Das Rauschen wird hier nur grob gefiltert;
    den Rest erledigt das Zusammenfassen über Dokumente hinweg, denn ein Listenpunkt
    aus einem einzigen Lastenheft findet kein Gegenstück.
    """
    roh: dict[tuple[str, str], Ueberschrift] = {}
    zuletzt: Ueberschrift | None = None
    for s_nr, seite in enumerate(seiten, start=1):
        for zeile in seite.splitlines():
            m = _KOPF.match(zeile)
            if not m or _TOC.search(zeile) or "|" in zeile or _DATUM.search(zeile):
                if zuletzt is not None:
                    zuletzt.eigener_text += len(zeile.strip())
                continue
            nr, titel = m.group(1), m.group(2).strip().rstrip(":").strip()
            zeichen = [c for c in titel if not c.isspace()]
            if (len(titel.split()) > 9 or titel.endswith((".", ",", ";"))
                    or any(c in titel for c in "[]{}<>=")
                    or sum(c.isalpha() for c in zeichen) < 0.7 * len(zeichen)
                    or sum(c.isdigit() for c in titel) > 4
                    or int(nr.split(".")[0]) > 30
                    or sum(c.isalpha() for c in titel) < 4):
                if zuletzt is not None:
                    zuletzt.eigener_text += len(zeile.strip())
                continue
            # Das Inhaltsverzeichnis nennt dieselbe Überschrift früher; die
            # Fundstelle mit Inhalt ist die spätere.
            zuletzt = roh[(nr, titel.lower())] = Ueberschrift(nr, titel, s_nr)

    liste = sorted(roh.values(), key=lambda u: (u.seite, [int(x) for x in u.nr.split(".")]))
    nummern = {u.nr for u in liste}
    titel_je_nr = {u.nr: u.titel for u in liste}
    for i, u in enumerate(liste):
        u.position = i / max(len(liste) - 1, 1)
        u.container = any(n.startswith(u.nr + ".") for n in nummern)
        if "." in u.nr:
            u.eltern = titel_je_nr.get(u.nr.rsplit(".", 1)[0], "")
    return liste


def quellen_laden(dateien: list[Path], melden=None) -> list[Quelle]:
    from src.dokumente.pdf_loader import _chunks_from_pages

    quellen = []
    for i, pfad in enumerate(dateien, start=1):
        if melden:
            melden(i, len(dateien), f"Lese {pfad.name}")
        seiten = seiten_laden(pfad)
        quellen.append(Quelle(
            kennung=musterdocx.kennung(pfad.name), pfad=pfad, seiten=seiten,
            chunks=_chunks_from_pages(seiten, pfad, "historisch"),
            ueberschriften=ueberschriften(seiten)))
    return quellen


def _einbetten(texte: list[str]) -> np.ndarray:
    from src.dokumente.vector_store import _get_model, normalize_rows
    if not texte:
        return np.zeros((0, 1), dtype=np.float32)
    vek = _get_model().encode(texte, batch_size=64, show_progress_bar=False)
    return normalize_rows(np.asarray(vek, dtype=np.float32))


# ── Phase 1: Gliederung vorschlagen ───────────────────────────────────────────

BENENNEN_PROMPT = """Die folgenden Kapitelüberschriften stammen aus verschiedenen
Kundenlastenheften für @@GEGENSTAND@@. Sie behandeln vermutlich dasselbe Thema.

@@LISTE@@

Gib EINEN kurzen deutschen Titel für dieses Thema, so wie er in einem
Musterlastenheft als Abschnittsüberschrift stünde. Höchstens acht Wörter, keine
Nummer, kein Satzzeichen am Ende, keine Firmennamen.

Antworte nur mit JSON: {"titel": "<Titel>"}"""

KAPITEL_PROMPT = """Die folgenden Abschnitte sollen in einem Musterlastenheft für
@@GEGENSTAND@@ auf Kapitel verteilt werden.

@@LISTE@@

Schlage 6 bis 10 Kapitel vor, wie sie in einem Lastenheft üblich sind (zum
Beispiel Allgemeines, Projektabwicklung, Konstruktion, Werkstoffe, Fertigung,
Prüfung und Abnahme, Dokumentation). Kurze deutsche Titel, höchstens vier
Wörter, in der Reihenfolge, in der sie im Lastenheft stehen sollen.

Antworte nur mit JSON: {"kapitel": ["<Titel 1>", "<Titel 2>"]}"""

ZUORDNUNG_PROMPT = """Ordne jeden Abschnitt eines Musterlastenhefts für @@GEGENSTAND@@
genau einem Kapitel zu.

KAPITEL:
@@KAPITEL@@

ABSCHNITTE:
@@LISTE@@

Antworte nur mit JSON. Schlüssel ist die Nummer des Abschnitts, Wert die Nummer
des Kapitels, zum Beispiel {"1": 2, "2": 5}."""

KAPITEL_JE_AUFRUF = 20


def _json_titel(antwort, rueckfall: str, max_woerter: int) -> str:
    from src.pruefung.kriterien import _first_json
    if antwort is not None and antwort.ok:
        blob = _first_json(antwort.text)
        try:
            t = str(json.loads(blob).get("titel", "")).strip() if blob else ""
        except (json.JSONDecodeError, AttributeError):
            t = ""
        t = re.sub(r"^\d+(\.\d+)*\s+", "", t).strip(" .:;")
        if 2 <= len(t) <= 90 and len(t.split()) <= max_woerter + 2:
            return t
    return rueckfall


def _haeufigster(titel: list[str]) -> str:
    """Rückfall ohne Modell: der häufigste, bei Gleichstand der kürzeste Titel."""
    from collections import Counter
    zaehler = Counter(t.strip() for t in titel)
    return sorted(zaehler.items(), key=lambda kv: (-kv[1], len(kv[0])))[0][0]


def _je_dokument_trennen(gruppen: np.ndarray, kennungen: list[str]) -> np.ndarray:
    """Zwei Überschriften DESSELBEN Lastenhefts landen nie im selben Thema.

    Zusammengefasst wird nur über Dokumente hinweg: „Schutzart" aus Lastenheft
    A und „Schutzart" aus B sind ein Thema. Hat ein Lastenheft zwei ähnliche
    Kapitel („Kerne" und „Kernzüge"), hat der Kunde sie bewusst getrennt — sie
    zu verschmelzen hieße, ein Kriterium zu verlieren. Bei einem einzigen
    Lastenheft übernimmt das dessen Gliederung damit unverändert.

    Die k-te Überschrift eines Dokuments innerhalb einer Gruppe geht in die
    k-te Teilgruppe.
    """
    neu = np.empty(len(gruppen), dtype=int)
    zaehler: dict[tuple[int, str], int] = {}
    teilgruppen: dict[tuple[int, int], int] = {}
    for i, (g, k) in enumerate(zip(gruppen, kennungen)):
        rang = zaehler.get((int(g), k), 0)
        zaehler[(int(g), k)] = rang + 1
        neu[i] = teilgruppen.setdefault((int(g), rang), len(teilgruppen))
    return neu


def gliederung_vorschlagen(quellen: list[Quelle], gegenstand: str,
                           modell: str = MODELL, chat=None, melden=None,
                           schwelle: float = AEHNLICH_UEBERSCHRIFT,
                           min_belege: int = MIN_BELEGE) -> list[dict]:
    """Schlägt Kapitel und Kriterien vor. Rückgabe: Zeilen für die Prüfung."""
    from sklearn.cluster import AgglomerativeClustering
    from src.pruefung.kriterien import _chat

    chat = chat or _chat
    melden = melden or (lambda *a: None)

    # Container („2 Technische Anforderungen" über 2.1, 2.2, …) sind Gliederung,
    # kein Thema — es sei denn, unter der Überschrift steht vor dem ersten
    # Unterkapitel eigener Text. Dann regelt das Kapitel selbst etwas, und weil
    # jedes Thema übernommen wird, darf es nicht wegfallen.
    # Knappe Blatt-Titel („Bearbeitung") bekommen den Elterntitel mit.
    eintraege = []
    for q in quellen:
        for u in q.ueberschriften:
            if u.container and u.eigener_text < MIN_EIGENER_TEXT:
                continue
            text = f"{u.eltern} – {u.titel}" if u.eltern and len(u.titel.split()) <= 2 else u.titel
            eintraege.append((q.kennung, u, text))
    if not eintraege:
        return []

    melden(0, 1, f"Fasse {len(eintraege)} Überschriften zu Themen zusammen")
    vek = _einbetten([t for _, _, t in eintraege])
    gruppen = (AgglomerativeClustering(
        n_clusters=None, metric="cosine", linkage=VERKNUEPFUNG,
        distance_threshold=1 - schwelle).fit_predict(vek)
        if len(eintraege) > 1 else np.zeros(1, dtype=int))
    gruppen = _je_dokument_trennen(gruppen, [k for k, _, _ in eintraege])

    themen = []
    for g in sorted(set(gruppen)):
        idx = [i for i, x in enumerate(gruppen) if x == g]
        belege = sorted({eintraege[i][0] for i in idx})
        if len(belege) < min_belege:
            continue
        if all(_norm(eintraege[i][1].titel) in GENERISCH for i in idx):
            continue
        themen.append({
            "belegt_in": belege,
            "beispiele": [f"{eintraege[i][1].titel} ({eintraege[i][0]})" for i in idx][:8],
            "titel_roh": [eintraege[i][1].titel for i in idx],
            "position": float(np.median([eintraege[i][1].position for i in idx])),
            "vektor": vek[idx].mean(axis=0),
        })
    if not themen:
        return []

    for i, t in enumerate(themen, start=1):
        melden(i, len(themen), f"Benenne Thema {i} von {len(themen)}")
        # Eine einzige Überschrift braucht keinen Namen vom Modell — sie hat einen.
        # Seit jedes Thema übernommen wird, ist das die Mehrzahl, und jeder gesparte
        # Aufruf ist Laufzeit.
        if len({_norm(x) for x in t["titel_roh"]}) == 1:
            t["titel"] = t["titel_roh"][0]
            continue
        liste = "\n".join(f"- {b}" for b in dict.fromkeys(t["titel_roh"]))
        antwort = chat(modell, BENENNEN_PROMPT.replace("@@GEGENSTAND@@", gegenstand)
                       .replace("@@LISTE@@", liste), 80)
        t["titel"] = _json_titel(antwort, _haeufigster(t["titel_roh"]), 8)

    kapitel_je_thema, kapitelnamen = _kapitel(themen, gegenstand, modell, chat, melden)

    kapitel_position = {kap: float(np.median([t["position"] for t, c in zip(themen, kapitel_je_thema)
                                              if c == kap]))
                        for kap in kapitelnamen}
    zeilen = []
    for t, kap in zip(themen, kapitel_je_thema):
        zeilen.append({
            "aktiv": True,
            "kapitel": kapitelnamen[kap],
            "titel": t["titel"],
            "belegt_in": t["belegt_in"],
            "beispiele": t["beispiele"],
            "_sortierung": (kapitel_position[kap], t["position"]),
        })
    zeilen.sort(key=lambda z: z.pop("_sortierung"))
    for i, z in enumerate(zeilen, start=1):
        z["id"] = f"T{i:03d}"
    return zeilen


def _kapitel(themen: list[dict], gegenstand: str, modell: str, chat, melden):
    """Verteilt die Themen auf Kapitel.

    Zuerst ohne Modell versucht und verworfen: Gruppierung nach Bedeutungsnähe.
    An Druckguss landeten fast alle Themen in einem Kapitel — Einwort-Titel wie
    „Kerne", „Garantie", „Termine" liegen im Einbettungsraum zu dicht, um sich
    zu trennen. Kapitel zu bilden ist eine Ordnungsaufgabe mit Weltwissen, und
    genau dafür taugt das Sprachmodell. Die Bedeutungsgruppierung bleibt als
    Rückfall, wenn es keine brauchbare Antwort gibt.
    """
    from sklearn.cluster import KMeans
    from src.pruefung.kriterien import _first_json

    def json_von(antwort):
        if antwort is None or not antwort.ok:
            return None
        blob = _first_json(antwort.text)
        try:
            return json.loads(blob) if blob else None
        except json.JSONDecodeError:
            return None

    melden(0, 1, "Schlage Kapitel vor")
    liste = "\n".join(f"- {t['titel']}" for t in themen)
    antwort = chat(modell, KAPITEL_PROMPT.replace("@@GEGENSTAND@@", gegenstand)
                   .replace("@@LISTE@@", liste), 200)
    daten = json_von(antwort)
    namen = [str(n).strip() for n in (daten or {}).get("kapitel", []) if str(n).strip()] \
        if isinstance(daten, dict) else []
    namen = list(dict.fromkeys(re.sub(r"^\d+\.?\s*", "", n) for n in namen))[:12]

    if len(namen) >= 2:
        zuordnung: dict[int, int] = {}
        kapitel_liste = "\n".join(f"{i}. {n}" for i, n in enumerate(namen, start=1))
        for start in range(0, len(themen), KAPITEL_JE_AUFRUF):
            teil = themen[start:start + KAPITEL_JE_AUFRUF]
            melden(start + len(teil), len(themen), "Ordne Themen Kapiteln zu")
            abschnitte = "\n".join(f"{start + i}. {t['titel']}" for i, t in enumerate(teil, start=1))
            daten = json_von(chat(modell, ZUORDNUNG_PROMPT.replace("@@GEGENSTAND@@", gegenstand)
                                  .replace("@@KAPITEL@@", kapitel_liste)
                                  .replace("@@LISTE@@", abschnitte), 400))
            for schluessel, wert in (daten.items() if isinstance(daten, dict) else []):
                try:
                    a, k = int(schluessel), int(wert)
                except (TypeError, ValueError):
                    continue
                if 1 <= a <= len(themen) and 1 <= k <= len(namen):
                    zuordnung[a - 1] = k - 1
        if len(zuordnung) >= 0.8 * len(themen):
            # Nicht zugeordnete Themen zum Kapitel ihres bedeutungsnächsten Nachbarn.
            zentren = np.vstack([t["vektor"] for t in themen])
            je_thema = []
            for i in range(len(themen)):
                if i in zuordnung:
                    je_thema.append(zuordnung[i])
                    continue
                nachbarn = [j for j in np.argsort(-(zentren @ zentren[i])) if j in zuordnung]
                je_thema.append(zuordnung[nachbarn[0]] if nachbarn else 0)
            benutzt = sorted(set(je_thema))
            return np.array(je_thema), {k: namen[k] for k in benutzt}

    # Rückfall ohne Modell
    zentren = np.vstack([t["vektor"] for t in themen])
    k = max(1, min(len(themen), 10, max(3, round(len(themen) / 8))))
    je_thema = (KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(zentren)
                if k > 1 else np.zeros(len(themen), dtype=int))
    return je_thema, {kap: f"Kapitel {j}" for j, kap in enumerate(sorted(set(je_thema)), start=1)}


def nummerieren(zeilen: list[dict]) -> list[dict]:
    """Vergibt Kapitel- und Kriteriumsnummern in der geprüften Reihenfolge.

    Die Nummern entstehen erst hier, nicht im Vorschlag: Wer in der Prüfung
    Zeilen streicht oder Kapitel umbenennt, soll keine Lücken erben.
    """
    aktiv = [z for z in zeilen if z.get("aktiv", True) and str(z.get("titel", "")).strip()]
    kapitel: dict[str, int] = {}
    zaehler: dict[int, int] = {}
    for z in aktiv:
        name = str(z.get("kapitel") or "Allgemeines").strip()
        k = kapitel.setdefault(name, len(kapitel) + 1)
        zaehler[k] = zaehler.get(k, 0) + 1
        z["kapitel"], z["kapitel_nr"], z["nr"] = name, str(k), f"{k}.{zaehler[k]}"
    return aktiv


# ── Phase 3: Inhalte erzeugen ─────────────────────────────────────────────────

INHALT_PROMPT = """Du erstellst einen Abschnitt eines Musterlastenhefts für @@GEGENSTAND@@.
Ein Musterlastenheft fasst zusammen, was Kunden in ihren Lastenheften zu einem
Thema üblicherweise fordern. Es ist neutral formuliert und nennt keine Firmen.

KAPITEL: @@KAPITEL@@
ABSCHNITT: @@TITEL@@

STELLEN AUS @@ANZAHL@@ KUNDENLASTENHEFTEN, jeweils mit Kennung in eckigen Klammern:

@@STELLEN@@

## Aufgabe

1. standardanforderungen — 1 bis 8 Sätze: Was fordern die Lastenhefte zu diesem
   Thema? Übernimm JEDE Anforderung aus den Stellen, auch wenn sie nur in einem
   Lastenheft steht. Was mehrere gleich fordern, fasse zu einem Satz zusammen.
   Verbindlich und neutral formuliert („… wird …", „… ist vorzulegen"). Keine
   Firmennamen, keine Kennungen. Statt Firmen: Auftraggeber, Auftragnehmer.
2. auspraegungen — konkrete Werte, Normen, Fabrikate, Fristen oder Sonderfälle
   aus einzelnen Lastenheften. Jede Angabe endet mit der Kennung genau des
   Lastenhefts, in dessen Stelle sie steht, in runden Klammern. Zahlen so, wie
   sie dort stehen. Nur was in den Stellen steht.
3. platzhalter — Angaben zu DIESEM Abschnitt, die je Projekt festzulegen sind,
   als kurze Substantive.
4. abgleichbegriffe — 5 bis 8 Fachbegriffe zu diesem Thema, geschrieben wie in
   den Stellen.

Antworte nur mit einem JSON-Objekt, ohne umgebenden Text:

{"standardanforderungen": [], "auspraegungen": [], "platzhalter": [], "abgleichbegriffe": []}"""

MAX_ZEICHEN_JE_QUELLE = 1200
MAX_QUELLEN_JE_ABSCHNITT = 8


def _norm(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.lower()))


def _stellen(zeile: dict, quellen: list[Quelle], anfrage: np.ndarray,
             chunk_vek: dict[str, np.ndarray]) -> tuple[list[str], list[tuple[str, str]]]:
    """Belegende Lastenhefte und ihre Stellen zu einem Kriterium.

    Zwei Wege, in dieser Reihenfolge:
    - Hat das Lastenheft eine Überschrift zum Thema, gilt es als belegend, und
      die Stelle ist der Text unter dieser Überschrift.
    - Sonst die ähnlichste Stelle des Dokuments, sofern sie über AEHNLICH_BELEG
      liegt.
    """
    from src.pruefung.kriterien import ist_verzeichnis

    beispiele = zeile.get("beispiele") or []
    titel_je_quelle: dict[str, list[str]] = {}
    for b in beispiele:
        m = re.match(r"^(.*) \(([^()]*)\)$", b)
        if m:
            titel_je_quelle.setdefault(m.group(2), []).append(m.group(1))

    belegt, stellen = [], []
    for q in quellen:
        text = ""
        if q.kennung in titel_je_quelle and q.kennung in (zeile.get("belegt_in") or []):
            ziel = {_norm(t) for t in titel_je_quelle[q.kennung]}
            for i, c in enumerate(q.chunks):
                # Das Inhaltsverzeichnis nennt den Titel zuerst; selten, aber dann sähe das
                # Modell eine Verzeichniszeile statt des Abschnitts.
                if ist_verzeichnis(c.text):
                    continue
                if any(z and z in _norm(c.text) for z in ziel):
                    text = " ".join(x.text for x in q.chunks[i:i + 3])
                    break
        vek = chunk_vek.get(q.kennung)
        if vek is not None and len(vek):
            scores = vek @ anfrage
            bester = int(np.argmax(scores))
            if not text and scores[bester] >= AEHNLICH_BELEG and not ist_verzeichnis(q.chunks[bester].text):
                text = " ".join(x.text for x in q.chunks[bester:bester + 2])
        if text or q.kennung in (zeile.get("belegt_in") or []):
            belegt.append(q.kennung)
        if text:
            # Stellen unter einer eigenen Überschrift zuerst, dann nach Ähnlichkeit.
            gewicht = 2.0 if q.kennung in titel_je_quelle and q.kennung in (zeile.get("belegt_in") or []) \
                else float(scores[bester]) if vek is not None and len(vek) else 0.0
            stellen.append((gewicht, q.kennung, " ".join(text.split())[:MAX_ZEICHEN_JE_QUELLE]))
    stellen.sort(key=lambda s: -s[0])
    return belegt, [(k, t) for _, k, t in stellen[:MAX_QUELLEN_JE_ABSCHNITT]]


_ZAHL = re.compile(r"\d+(?:[.,]\d+)*")


def _zahlen(text: str) -> set[str]:
    return {z.replace(".", "").replace(",", "") for z in _ZAHL.findall(text)}


def _in_quelle_belegt(auspraegung: str, stellen: list[tuple[str, str]], kennungen: list[str]) -> bool:
    """Steht die Ausprägung in der Stelle genau des Lastenhefts, das sie nennt?

    Anlass: Eine Ausprägung kann eine echte Kennung tragen und doch aus dem
    Prompt stammen, oder ein Lastenheft nennen, in dessen Stelle sie nicht
    vorkommt. Eine Kennung allein belegt nichts.

    Zahlen müssen wörtlich in der Stelle stehen (Tausender- und Dezimalzeichen
    gleichgesetzt, OCR schreibt beides). Ohne Zahlen muss die Hälfte der Wörter
    dort vorkommen — eine sinngemäße Wiedergabe soll bestehen.
    """
    # Satzzeichen hinter der Klammer zulassen: Ohne Formatbeispiel im Prompt
    # schreibt das Modell „… (Kennung).“ — sonst würden vollständig belegte
    # Ausprägungen verworfen.
    m = re.search(r"\(([^()]*)\)[\s.;,:!?]*$", auspraegung)
    if not m:
        return False
    kennung = m.group(1).strip()
    je_doc = dict(stellen)
    if kennung not in kennungen or kennung not in je_doc:
        return False
    text = auspraegung[:m.start()]
    quelle = je_doc[kennung].lower()
    zahlen = {z for z in _zahlen(text) if len(z) >= 2}
    if zahlen:
        return zahlen <= _zahlen(quelle)
    woerter = set(re.findall(r"[\wÄÖÜäöüß]{4,}", text.lower()))
    return bool(woerter) and len({w for w in woerter if w in quelle}) >= 0.5 * len(woerter)


def _pruefen(daten: dict, stellen: list[tuple[str, str]], kennungen: list[str],
             titel: str) -> dict:
    """Behält von der Modellantwort nur, was sich gegen die Stellen halten lässt."""
    def liste(schluessel):
        wert = daten.get(schluessel) if isinstance(daten, dict) else None
        return [" ".join(str(x).split()) for x in (wert or []) if str(x).strip()]

    quelltext = " ".join(t for _, t in stellen).lower()
    kenn = sorted(kennungen, key=len, reverse=True)

    anforderungen = [s for s in liste("standardanforderungen")
                     if len(s) >= 15 and not any(k.lower() in s.lower() for k in kenn)][:8]

    auspraegungen = [a for a in liste("auspraegungen") if _in_quelle_belegt(a, stellen, kenn)]

    platzhalter = [p.strip("[]() ") for p in liste("platzhalter")
                   if 0 < len(p.split()) <= 6][:8]

    begriffe = []
    for b in liste("abgleichbegriffe"):
        if b.lower() in quelltext or b.lower() in titel.lower():
            if b.lower() not in {x.lower() for x in begriffe}:
                begriffe.append(b)
    if len(begriffe) < 3:
        for w in re.findall(r"[A-Za-zÄÖÜäöüß-]{5,}", titel):
            if w.lower() not in {x.lower() for x in begriffe}:
                begriffe.append(w)
    return {"standardanforderungen": anforderungen, "auspraegungen": auspraegungen,
            "platzhalter": platzhalter, "abgleichbegriffe": begriffe[:8]}


def _chunk_vektoren(stand: Arbeitsstand, q: Quelle) -> np.ndarray:
    """Abschnittsvektoren eines Lastenhefts, im Arbeitsordner zwischengespeichert.

    Das Einbetten dauert bei vielen Lastenheften mehrere Minuten — bei jedem
    Start von „Inhalte erzeugen“, also auch nach jedem Abbruch, gegen den das
    Aufsetzen gerade Zeit sparen soll. Der Schlüssel ist derselbe Inhalts-Hash
    wie beim OCR-Zwischenspeicher.
    """
    from src.pruefung.kriterien import ist_verzeichnis
    from src.dokumente.pdf_loader import _cache_schluessel
    from src.dokumente.vector_store import MODELL_NAME

    ziel = stand.ordner / "vektoren" / f"{_cache_schluessel(q.pfad)}.npz"
    if ziel.exists():
        try:
            d = np.load(ziel)
            if int(d["n"]) == len(q.chunks) and str(d["modell"]) == MODELL_NAME:
                return d["v"]
        except (OSError, KeyError, ValueError):
            pass
    v = _einbetten([c.text for c in q.chunks])
    # Verzeichniszeilen sollen nie die ähnlichste Stelle sein.
    for j, c in enumerate(q.chunks):
        if ist_verzeichnis(c.text):
            v[j] = 0
    ziel.parent.mkdir(parents=True, exist_ok=True)
    np.savez(ziel, v=v, n=len(q.chunks), modell=MODELL_NAME)
    return v


def inhalte_erzeugen(stand: Arbeitsstand, quellen: list[Quelle], zeilen: list[dict],
                     gegenstand: str, modell: str = MODELL, chat=None,
                     melden=None) -> dict[str, dict]:
    """Füllt jedes Kriterium. Setzt nach einem Abbruch auf dem Gesicherten auf."""
    from src.pruefung.kriterien import _chat, _first_json

    chat = chat or _chat
    melden = melden or (lambda *a: None)
    fertig = stand.lesen(stand.inhalte, {}) or {}
    kennungen = [q.kennung for q in quellen]

    chunk_vek = {}
    for i, q in enumerate(quellen, start=1):
        melden(i, len(quellen), f"Bette {q.kennung} ein")
        chunk_vek[q.kennung] = _chunk_vektoren(stand, q)

    anfragen = _einbetten([f"{z['titel']}. " + " ".join(re.sub(r" \([^()]*\)$", "", b)
                                                        for b in (z.get("beispiele") or [])[:5])
                           for z in zeilen])

    for n, (z, anfrage) in enumerate(zip(zeilen, anfragen), start=1):
        schluessel = z["id"]
        alt = fertig.get(schluessel)
        if alt and alt.get("titel") == z["titel"] and alt.get("status") == "ok":
            continue
        melden(n, len(zeilen), f"{z['nr']} {z['titel']}")

        belegt, stellen = _stellen(z, quellen, anfrage, chunk_vek)
        eintrag = {"titel": z["titel"], "belegt_in": belegt, "status": "ok", "fehler": "",
                   "quellen": [k for k, _ in stellen],
                   "standardanforderungen": [], "auspraegungen": [], "platzhalter": [],
                   "abgleichbegriffe": []}
        if not stellen:
            eintrag.update(status="leer", fehler="keine passende Stelle in den Lastenheften")
        else:
            prompt = (INHALT_PROMPT.replace("@@GEGENSTAND@@", gegenstand)
                      .replace("@@KAPITEL@@", z["kapitel"]).replace("@@TITEL@@", z["titel"])
                      .replace("@@ANZAHL@@", str(len(stellen)))
                      .replace("@@STELLEN@@", "\n\n".join(f"[{k}] {t}" for k, t in stellen)))
            antwort = chat(modell, prompt, 1400)
            blob = _first_json(antwort.text) if antwort.ok else None
            try:
                daten = json.loads(blob) if blob else None
            except json.JSONDecodeError:
                daten = None
            if daten is None:
                eintrag.update(status="fehler",
                               fehler=antwort.grund if not antwort.ok else "Antwort ohne gültiges JSON")
            else:
                eintrag.update(_pruefen(daten, stellen, kennungen, z["titel"]))
                # Die unveränderte Antwort bleibt daneben stehen: Wer eine
                # verworfene Ausprägung vermisst, sieht nach, statt neu zu rechnen.
                eintrag["roh"] = daten
        fertig[schluessel] = eintrag
        stand.schreiben(stand.inhalte, fertig)
    return fertig


def entwurf_bauen(zeilen: list[dict], inhalte: dict[str, dict], kennungen: list[str],
                  gegenstand: str) -> musterdocx.Entwurf:
    kriterien, ohne = [], []
    for z in zeilen:
        i = inhalte.get(z["id"]) or {}
        if i.get("status") != "ok" or not i.get("standardanforderungen"):
            ohne.append(f"{z['nr']} {z['titel']}")
        kriterien.append(musterdocx.Kriterium(
            nr=z["nr"], titel=z["titel"], kapitel_nr=z["kapitel_nr"], kapitel_titel=z["kapitel"],
            belegt_in=[k for k in (i.get("belegt_in") or z.get("belegt_in") or []) if k in kennungen],
            standardanforderungen=i.get("standardanforderungen") or [],
            auspraegungen=i.get("auspraegungen") or [],
            platzhalter=i.get("platzhalter") or [],
            abgleichbegriffe=i.get("abgleichbegriffe") or [z["titel"]]))

    hinweise = [
        "Die Gliederung wurde aus den Kapitelüberschriften der Lastenhefte vorgeschlagen "
        "und vor dem Befüllen geprüft. Aufgenommen wurde jedes Thema, auch wenn es nur "
        "ein Lastenheft behandelt; die Häufigkeit steht in der Einstufung.",
        "Belegzahl und Einstufung sind eine grobe Schätzung: Ein Lastenheft gilt als "
        "belegend, wenn es eine eigene Überschrift zum Thema oder eine ähnliche Stelle "
        "enthält.",
        "Standardanforderungen sind Modelltext und fachlich zu prüfen. Ausprägungen wurden "
        "gegen die Stelle des genannten Lastenhefts geprüft (Zahlen wörtlich), "
        "Abgleichbegriffe gegen die Quellstellen.",
        "Ausprägungen können Hersteller, Typen und Werknormen der Quelllastenhefte "
        "nennen. Vor einer Weitergabe auf Kunden- und Firmennamen durchsehen.",
    ]
    if len(kennungen) == 1:
        hinweise.append("Abgeleitet aus einem einzigen Lastenheft: Jeder Abschnitt ist darin "
                        "belegt und deshalb als Pflicht eingestuft. Über die Häufigkeit sagt "
                        "die Einstufung erst etwas, wenn weitere Lastenhefte hinzukommen.")
    if ohne:
        hinweise.append(f"{len(ohne)} Abschnitte ohne erzeugte Standardanforderungen, von Hand "
                        f"zu ergänzen: " + "; ".join(ohne[:20]) + (" …" if len(ohne) > 20 else ""))
    return musterdocx.Entwurf(gegenstand=gegenstand, dokumente=kennungen,
                              kriterien=kriterien, hinweise=hinweise)


# ── Einstiegspunkte für CLI und Hintergrundlauf ───────────────────────────────

def lauf_vorschlag(stand: Arbeitsstand, gegenstand: str, modell: str = MODELL, chat=None) -> None:
    with lebenszeichen(stand):
        _lauf_vorschlag(stand, gegenstand, modell, chat)


def _lauf_vorschlag(stand: Arbeitsstand, gegenstand: str, modell: str, chat) -> None:
    try:
        stand.melden("vorschlag", 0, 1, "Lese Lastenhefte")
        quellen = quellen_laden(stand.dateien(),
                                lambda i, n, t: stand.melden("vorschlag", i, n, t))
        zeilen = gliederung_vorschlagen(
            quellen, gegenstand, modell, chat,
            melden=lambda i, n, t: stand.melden("vorschlag", i, n, t))
        stand.schreiben(stand.gliederung, {
            "gegenstand": gegenstand, "modell": modell,
            "erstellt": datetime.now().isoformat(timespec="seconds"),
            "dokumente": [q.kennung for q in quellen],
            "ueberschriften": {q.kennung: len(q.ueberschriften) for q in quellen},
            "geprueft": False, "zeilen": zeilen})
        if stand.inhalte.exists():
            stand.inhalte.unlink()       # neue Gliederung, alte Inhalte gelten nicht mehr
        text = (f"{len(zeilen)} Kriterien vorgeschlagen" if zeilen else
                "Keine Themen gefunden — Lastenhefte ohne nummerierte Überschriften?")
        stand.melden("vorschlag", 1, 1, text, fertig=True)
    except Exception as e:
        stand.melden("vorschlag", 0, 1, "Abgebrochen", fehler=f"{type(e).__name__}: {e}")
        raise


def lauf_inhalte(stand: Arbeitsstand, modell: str = MODELL, chat=None) -> Path:
    with lebenszeichen(stand):
        return _lauf_inhalte(stand, modell, chat)


def _lauf_inhalte(stand: Arbeitsstand, modell: str, chat) -> Path:
    try:
        g = stand.lesen(stand.gliederung)
        if not g or not g.get("zeilen"):
            raise ValueError("Keine Gliederung vorhanden — zuerst vorschlagen lassen.")
        zeilen = nummerieren(g["zeilen"])
        stand.melden("inhalte", 0, len(zeilen), "Lese Lastenhefte")
        quellen = quellen_laden(stand.dateien(),
                                lambda i, n, t: stand.melden("inhalte", 0, len(zeilen), t))
        inhalte = inhalte_erzeugen(stand, quellen, zeilen, g["gegenstand"], modell, chat,
                                   melden=lambda i, n, t: stand.melden("inhalte", i, n, t))
        entwurf = entwurf_bauen(zeilen, inhalte, [q.kennung for q in quellen], g["gegenstand"])
        ziel = musterdocx.schreiben(entwurf, stand.entwurf(g["gegenstand"]))
        stand.melden("inhalte", len(zeilen), len(zeilen), f"Entwurf geschrieben: {ziel.name}",
                     fertig=True)
        return ziel
    except Exception as e:
        stand.melden("inhalte", 0, 1, "Abgebrochen", fehler=f"{type(e).__name__}: {e}")
        raise
