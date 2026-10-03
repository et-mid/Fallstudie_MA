"""PDF loading and chunking for Lastenhefte."""

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from src.verzeichnisse import DATA_DIR

# 150 dpi laut Briefing ausreichend — und die Auflösung, mit der der OCR-Text
# hinter der Ground Truth erzeugt wurde. Höhere Werte kosten bei 100+ Seiten
# spürbar Zeit, ohne die Fundstellen zu verändern.
OCR_RESOLUTION = 150
OCR_LANG = "deu+eng"  # benötigt die Sprachpakete deu und eng in Tesseract

# Ausrichtungserkennung: Stichprobe statt Prüfung je Seite (Stapelscans sind
# durchgängig gleich ausgerichtet), grob gerendert. Der Schwellwert ist der
# Mindestanteil an Funktionswörtern, ab dem ein Winkel als „lesbar" gilt —
# aufrechter Fließtext liegt deutlich darüber, gedrehter bei null.
OCR_ORIENT_SAMPLE         = 3
OCR_ORIENT_RESOLUTION     = OCR_RESOLUTION
OCR_ORIENT_MIN_LESBARKEIT = 0.02

# Parallele Tesseract-Läufe und Blockgröße beim Rendern.
OCR_WORKERS = 4
OCR_BATCH   = 8

# Erkannter Text wird je Dokument zwischengespeichert. Ein 259-Seiten-Scan
# kostet sonst bei jedem Lauf mehrere Minuten, obwohl sich nichts geändert hat.
OCR_CACHE_DIR = DATA_DIR / "ocr_cache"

# Übliche Windows-Installationspfade — pytesseract findet das Binary sonst nur,
# wenn es im PATH liegt.
_TESSERACT_PFADE = (
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    Path.home() / r"AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
    Path.home() / r"AppData\Local\Tesseract-OCR\tesseract.exe",
)

_OCR_STATUS: tuple[bool, str] | None = None


class TextExtraktionsFehler(Exception):
    """Aus dem Dokument ließ sich kein Text gewinnen — mit konkreter Ursache."""


def ocr_status() -> tuple[bool, str]:
    """Prüft, ob OCR tatsächlich nutzbar ist — Programm, nicht nur Python-Paket.

    Das Paket `pytesseract` ist nur ein Wrapper; ohne installiertes Tesseract
    scheitert jeder Aufruf. Das Ergebnis wird einmal ermittelt und gemerkt.
    """
    global _OCR_STATUS
    if _OCR_STATUS is not None:
        return _OCR_STATUS

    try:
        import pytesseract
    except ImportError:
        _OCR_STATUS = (False, "Das Python-Paket pytesseract ist nicht installiert.")
        return _OCR_STATUS

    for pfad in _TESSERACT_PFADE:
        if pfad.exists():
            pytesseract.pytesseract.tesseract_cmd = str(pfad)
            break

    try:
        version = pytesseract.get_tesseract_version()
    except Exception:
        _OCR_STATUS = (False, (
            "Tesseract-OCR ist nicht installiert (das Python-Paket pytesseract allein "
            "genügt nicht). Windows-Installer: "
            "https://github.com/UB-Mannheim/tesseract/wiki — beim Setup die "
            "Sprachpakete German und English mitauswählen."))
        return _OCR_STATUS

    try:
        sprachen = set(pytesseract.get_languages())
    except Exception:
        sprachen = set()

    fehlend = {"deu", "eng"} - sprachen if sprachen else set()
    if fehlend:
        _OCR_STATUS = (False, (
            f"Tesseract {version} ist installiert, aber die Sprachpakete "
            f"{', '.join(sorted(fehlend))} fehlen. Über den Installer nachinstallieren "
            f"(Additional language data)."))
        return _OCR_STATUS

    _OCR_STATUS = (True, f"Tesseract {version}, Sprachen deu+eng.")
    return _OCR_STATUS


# Häufige deutsche und englische Funktionswörter. Kopfstehender Text erzeugt
# keine davon, aufrecht gelesener Fließtext dagegen zuverlässig viele.
_HAEUFIGE_WOERTER = frozenset("""
der die das und oder für von mit ist sind wird werden nicht auch nach bei zum zur
den dem des ein eine einer einem sowie sind muss müssen kann können sowie gemäß
the and for with are shall must not from this that will have been which used
""".split())


def _lesbarkeit(text: str, min_woerter: int = 15) -> float:
    """Anteil häufiger Funktionswörter am Text — Maß für „echte Sprache".

    Robuster als Tesseracts Konfidenzwert: Ein um 180° gedrehter Scan liefert
    Zeichenketten wie „ONIANLOVANNVIN", die keinerlei Funktionswörter enthalten,
    während OSD dafür durchaus hohe Konfidenz melden kann.

    `min_woerter` ist die Untergrenze, unterhalb derer der Anteil nicht mehr
    aussagekräftig ist und 0 zurückkommt. Für die Ausrichtungserkennung werden
    ganze Seiten geprüft, dort sind 15 Wörter angemessen. Wer einzelne
    Textabschnitte bewertet, muss den Wert senken — sonst gilt jeder kurze,
    vollständig lesbare Satz als unlesbar.
    """
    woerter = re.findall(r"[A-Za-zÄÖÜäöüß]{2,}", text.lower())
    if len(woerter) < min_woerter:
        return 0.0
    return sum(1 for w in woerter if w in _HAEUFIGE_WOERTER) / len(woerter)


def _orientierung_bestimmen(seiten: list) -> int:
    """Bestimmt die Ausrichtung des Dokuments durch Ausprobieren.

    Gescannte Lastenhefte liegen teilweise um 90°, 180° oder 270° verdreht vor.
    Ohne Korrektur liest Tesseract zeichengetreu Unsinn („pue" statt „and"), der
    fachlich nicht erkennbar ist und jede Ähnlichkeitssuche wertlos macht.

    Tesseracts OSD hat sich auf diesen Scans als unzuverlässig erwiesen — es
    meldete für dasselbe Dokument je nach Auflösung 90° oder 270°. Deshalb wird
    hier nicht gefragt, sondern gemessen: alle vier Winkel auf einer Stichprobe
    erkennen lassen und den mit dem lesbarsten Ergebnis nehmen.

    Ein Stapelscan hat durchgängig dieselbe Ausrichtung, eine Stichprobe genügt
    also für das ganze Dokument.
    """
    if not seiten:
        return 0

    # Über das Dokument verteilte Probeseiten. Der Text aller Proben wird je
    # Winkel ZUSAMMEN bewertet: Einzelne Seiten sind oft zu textarm für ein
    # belastbares Urteil (Deckblätter, Zeichnungen), in Summe reicht es.
    proben = [seiten[i * len(seiten) // (OCR_ORIENT_SAMPLE + 1)]
              for i in range(1, OCR_ORIENT_SAMPLE + 1)]

    bilder = []
    for page in proben:
        try:
            bilder.append(page.to_image(resolution=OCR_ORIENT_RESOLUTION).original)
        except Exception:
            pass
    if not bilder:
        return 0

    bester_winkel, bester_wert = 0, 0.0
    with ThreadPoolExecutor(max_workers=OCR_WORKERS) as pool:
        for winkel in (0, 90, 180, 270):
            texte = pool.map(lambda b, w=winkel: _ocr_bild(b, w), bilder)
            wert = _lesbarkeit(" ".join(texte))
            if wert > bester_wert:
                bester_winkel, bester_wert = winkel, wert

    # Kein Winkel liefert lesbaren Text — unrotiert lassen statt raten.
    return bester_winkel if bester_wert >= OCR_ORIENT_MIN_LESBARKEIT else 0


def _ocr_bild(bild, winkel: int) -> str:
    """Erkennt den Text eines bereits gerenderten Seitenbildes.

    Ruft ocr_status() auf, weil dort der Pfad zum Tesseract-Programm gesetzt
    wird. Ohne diesen Aufruf scheitert jede Erkennung stillschweigend — die
    Funktion darf nicht von der Aufrufreihenfolge abhängen. Das Ergebnis ist
    gemerkt, der Aufruf kostet also nichts.
    """
    if not ocr_status()[0]:
        return ""
    import pytesseract
    if winkel:
        # image_to_osd nennt den Winkel, um den GEDREHT WERDEN MUSS (im
        # Uhrzeigersinn); PIL dreht gegen den Uhrzeigersinn.
        bild = bild.rotate(-winkel, expand=True)
    try:
        return pytesseract.image_to_string(bild, lang=OCR_LANG)
    except Exception:
        return ""


def _ocr_seiten(seiten: list, indizes: list[int], winkel: int) -> dict[int, str]:
    """Erkennt den Text mehrerer Seiten, mehrere Tesseract-Läufe parallel.

    Tesseract läuft als eigener Prozess; während des Wartens gibt Python die
    GIL frei, Threads genügen also. Gerendert wird in Blöcken, damit bei
    200+ Seiten nicht alle Bilder gleichzeitig im Speicher liegen.
    """
    ergebnis: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=OCR_WORKERS) as pool:
        for start in range(0, len(indizes), OCR_BATCH):
            block = indizes[start:start + OCR_BATCH]
            bilder = []
            for i in block:
                try:
                    bilder.append((i, seiten[i].to_image(resolution=OCR_RESOLUTION).original))
                except Exception:
                    ergebnis[i] = ""
            futures = {pool.submit(_ocr_bild, bild, winkel): i for i, bild in bilder}
            for future, i in futures.items():
                ergebnis[i] = future.result()
    return ergebnis


@dataclass
class DocumentChunk:
    text: str
    page: int
    source_file: str
    chunk_index: int
    kind: str = "historisch"  # "muster" | "historisch" | "norm"


# Ziel-/Grenzwerte für die Chunk-Größe (in Zeichen)
MIN_CHUNK   = 40    # kürzere Blöcke werden mit dem nächsten zusammengeführt
TARGET_CHUNK = 500  # angestrebte Chunk-Länge
MAX_CHUNK   = 900   # harte Obergrenze


def _split_page(text: str) -> list[str]:
    """Teilt einen Seitentext in sinnvolle Absätze.

    pdfplumber liefert meist nur einfache Zeilenumbrüche, selten doppelte.
    Daher: an Leerzeilen trennen, ansonsten Zeilen akkumulieren bis die
    Ziel-Länge erreicht ist. Sehr kurze Blöcke werden zusammengeführt.
    """
    lines = text.split("\n")
    paragraphs: list[str] = []
    buf: list[str] = []
    buf_len = 0

    def flush():
        nonlocal buf, buf_len
        if buf:
            joined = " ".join(buf).strip()
            if joined:
                paragraphs.append(joined)
            buf = []
            buf_len = 0

    for raw in lines:
        line = raw.strip()
        if not line:
            # Leerzeile = harter Absatztrenner
            flush()
            continue
        buf.append(line)
        buf_len += len(line) + 1
        # Bei Erreichen der Ziel-Länge an einem Zeilenende trennen
        if buf_len >= TARGET_CHUNK:
            flush()

    flush()

    # Sehr lange Blöcke (z.B. Tabellen ohne Umbrüche) hart unterteilen
    sized: list[str] = []
    for p in paragraphs:
        if len(p) <= MAX_CHUNK:
            sized.append(p)
        else:
            for i in range(0, len(p), MAX_CHUNK):
                sized.append(p[i:i + MAX_CHUNK].strip())

    # Zu kurze Blöcke mit dem vorherigen zusammenführen
    merged: list[str] = []
    for p in sized:
        if merged and len(p) < MIN_CHUNK:
            merged[-1] = (merged[-1] + " " + p).strip()
        elif merged and len(merged[-1]) < MIN_CHUNK:
            merged[-1] = (merged[-1] + " " + p).strip()
        else:
            merged.append(p)

    return [p for p in merged if len(p) >= MIN_CHUNK]


def _chunks_from_pages(pages: list[str], path: Path, kind: str) -> list[DocumentChunk]:
    """Wandelt seitenweisen Rohtext in DocumentChunks um (gemeinsam für PDF/DOCX)."""
    chunks = []
    chunk_index = 0
    for page_num, text in enumerate(pages, start=1):
        if not text:
            continue
        for para in _split_page(text):
            chunks.append(DocumentChunk(
                text=para,
                page=page_num,
                source_file=path.name,
                chunk_index=chunk_index,
                kind=kind,
            ))
            chunk_index += 1
    return chunks


def _cache_schluessel(path: Path) -> str:
    """Inhalts-Hash plus alle Parameter, die den erkannten Text beeinflussen."""
    h = hashlib.sha1()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    h.update(f"|{OCR_RESOLUTION}|{OCR_LANG}|{OCR_ORIENT_MIN_LESBARKEIT}".encode())
    return h.hexdigest()


def _cache_lesen(path: Path) -> tuple[list[str], int, int] | None:
    datei = OCR_CACHE_DIR / f"{_cache_schluessel(path)}.json"
    if not datei.exists():
        return None
    try:
        d = json.loads(datei.read_text(encoding="utf-8"))
        return d["seiten"], d["seiten_gesamt"], d["ohne_textebene"]
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def _cache_schreiben(path: Path, seiten: list[str], gesamt: int, ohne: int) -> None:
    # Nur cachen, wenn OCR im Spiel war — reines Textextrahieren ist ohnehin schnell.
    if not ohne:
        return
    try:
        OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (OCR_CACHE_DIR / f"{_cache_schluessel(path)}.json").write_text(
            json.dumps({"quelle": path.name, "seiten_gesamt": gesamt,
                        "ohne_textebene": ohne, "seiten": seiten},
                       ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass  # Ein nicht beschreibbarer Cache darf den Lauf nicht verhindern.


def _seiten_lesen(path: Path) -> tuple[list[str], int, int]:
    """Liest ein PDF seitenweise, mit OCR für Seiten ohne Textebene."""
    with pdfplumber.open(path) as pdf:
        seiten = pdf.pages
        seiten_gesamt = len(seiten)
        texte: list[str] = []
        ocr_indizes: list[int] = []

        # Die Entscheidung fällt je Seite, nicht je Dokument: Ein gemischtes
        # PDF wird teils über die Textebene, teils über Texterkennung gelesen.
        #
        # Die Schwelle ist bewusst „nicht leer“ und nicht etwa „genug Text“: Seiten mit
        # wenig Text über einer Zeichnung bleiben bei der Textebene. Über die
        # Texterkennung kämen sonst Maßangaben und Beschriftungsfetzen in die Suche.
        for i, page in enumerate(seiten):
            text = page.extract_text() or ""
            texte.append(text)
            if not text.strip():
                ocr_indizes.append(i)

        if not ocr_indizes or not ocr_status()[0]:
            return texte, seiten_gesamt, len(ocr_indizes)

        winkel = _orientierung_bestimmen([seiten[i] for i in ocr_indizes])
        if winkel:
            print(f"  {path.name}: Scan um {winkel}° gedreht — wird vor der "
                  f"Texterkennung korrigiert.")
        print(f"  {path.name}: OCR über {len(ocr_indizes)} von {seiten_gesamt} Seiten…")

        for i, text in _ocr_seiten(seiten, ocr_indizes, winkel).items():
            texte[i] = text

    return texte, seiten_gesamt, len(ocr_indizes)


def load_pdf(path: Path, kind: str = "historisch") -> list[DocumentChunk]:
    """Extract text from PDF and split into chunks by page and paragraph.

    Liefert das PDF keinen Text und ist OCR nicht nutzbar, wird ein
    TextExtraktionsFehler mit der konkreten Ursache geworfen — sonst sähe ein
    fehlendes Tesseract genauso aus wie ein leeres Dokument.
    """
    zwischenspeicher = _cache_lesen(path)
    if zwischenspeicher is not None:
        pages, seiten_gesamt, ohne_textebene = zwischenspeicher
    else:
        try:
            pages, seiten_gesamt, ohne_textebene = _seiten_lesen(path)
        except Exception as e:
            # pdfminer wirft je nach Schaden PDFSyntaxError, PSEOF oder
            # PDFPasswordIncorrect. Für den Aufrufer ist es immer dasselbe:
            # aus dieser Datei ist kein Text zu gewinnen — und das soll als
            # Meldung ankommen, nicht als Traceback (gemessen an einer leeren
            # PDF: „No /Root object! - Is this really a PDF?" bis in die
            # Oberfläche durchgereicht).
            raise TextExtraktionsFehler(
                f"{path.name} lässt sich nicht als PDF lesen: {e}") from None
        _cache_schreiben(path, pages, seiten_gesamt, ohne_textebene)

    chunks = _chunks_from_pages(pages, path, kind)
    if chunks:
        return chunks

    ocr_ok, ocr_meldung = ocr_status()
    if ohne_textebene and not ocr_ok:
        raise TextExtraktionsFehler(
            f"{path.name} ist ein Scan ohne Textebene "
            f"({ohne_textebene} von {seiten_gesamt} Seiten) und OCR ist nicht "
            f"verfügbar. {ocr_meldung}")
    if ohne_textebene:
        raise TextExtraktionsFehler(
            f"{path.name}: OCR lief über {ohne_textebene} von {seiten_gesamt} "
            f"Seiten, erkannte aber keinen verwertbaren Text. Möglicherweise ist "
            f"die Scanqualität zu gering oder die Seiten sind gedreht.")
    raise TextExtraktionsFehler(
        f"{path.name} enthält Text, aber keine Abschnitte von mindestens "
        f"{MIN_CHUNK} Zeichen.")


def _docx_pages(path: Path) -> list[str]:
    """Liest ein Word-Dokument als Liste von Seitentexten.

    Word kennt keine festen Seiten ohne Rendering — als Näherung wird an
    expliziten Seitenumbrüchen getrennt. Tabellenzeilen werden als
    "Zelle | Zelle | …" übernommen, damit Parameter-Tabellen erhalten bleiben.
    """
    from docx import Document as DocxDocument
    from docx.oxml.ns import qn
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = DocxDocument(str(path))

    def has_page_break(paragraph: Paragraph) -> bool:
        for run in paragraph.runs:
            for br in run._element.findall(qn("w:br")):
                if br.get(qn("w:type")) == "page":
                    return True
        return False

    pages: list[str] = []
    current: list[str] = []

    for child in doc.element.body.iterchildren():
        if isinstance(child, CT_P):
            para = Paragraph(child, doc)
            if para.text.strip():
                current.append(para.text.strip())
            if has_page_break(para):
                pages.append("\n".join(current))
                current = []
        elif isinstance(child, CT_Tbl):
            for row in Table(child, doc).rows:
                cells = [c.text.strip() for c in row.cells]
                line = " | ".join(c for c in cells if c)
                if line:
                    current.append(line)

    pages.append("\n".join(current))
    return pages


def load_docx(path: Path, kind: str = "historisch") -> list[DocumentChunk]:
    """Extract text from a Word document and split it into chunks."""
    try:
        seiten = _docx_pages(path)
    except Exception as e:
        raise TextExtraktionsFehler(
            f"{path.name} lässt sich nicht als Word-Datei lesen: {e}") from None
    chunks = _chunks_from_pages(seiten, path, kind)
    if not chunks:
        raise TextExtraktionsFehler(
            f"{path.name} enthält keinen Text in Abschnitten von mindestens "
            f"{MIN_CHUNK} Zeichen.")
    return chunks


SUPPORTED_SUFFIXES = (".pdf", ".docx")


def load_document(path: Path, kind: str = "historisch") -> list[DocumentChunk]:
    """Lädt ein Dokument anhand seiner Endung (PDF oder Word).

    Ein nicht unterstütztes Format ist für den Aufrufer dasselbe wie eine
    unlesbare Datei: TextExtraktionsFehler, damit CLI und Oberfläche es mit
    derselben Ausnahme fangen.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return load_pdf(path, kind)
    if suffix == ".docx":
        return load_docx(path, kind)
    raise TextExtraktionsFehler(
        f"Nicht unterstütztes Dateiformat: {path.suffix} ({path.name}). "
        f"Erwartet: {', '.join(SUPPORTED_SUFFIXES)}.")


def load_all_documents(folder: Path, kind: str = "historisch") -> list[DocumentChunk]:
    """Load all supported documents (PDF/DOCX) from a folder."""
    files = [p for p in sorted(folder.iterdir())
             if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES]

    if not files:
        raise FileNotFoundError(f"Keine PDF-/Word-Dateien in {folder} gefunden.")

    all_chunks = []
    for path in files:
        all_chunks.extend(load_document(path, kind))

    return all_chunks
