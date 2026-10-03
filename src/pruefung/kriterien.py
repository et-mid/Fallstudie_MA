"""Kriterienbasierte Prüfung eines Kundenlastenhefts gegen den Standard.

Die Prüfung folgt der verbindlichen Gliederung aus 67 Kriterien
(data/struktur_kriterien.json). Der Vergleichsmaßstab je Kriterium steht in
data/Standard_Lastenheft_Chunks.jsonl — ein Chunk je Kriterium, direkt über die
Nummer zugeordnet. Für die Standardseite ist deshalb kein Retrieval nötig.

Je Kriterium ein LLM-Aufruf. Die Kandidaten-Fundstellen im GEPRÜFTEN Lastenheft
kommen aus einer hybriden Suche: Kosinus-Ähnlichkeit über die Embeddings plus
lexikalischer Bonus für Treffer der Abgleichbegriffe. Inhaltsverzeichnisse und
Kopf-/Fußzeilen werden vorher ausgesondert — laut Briefing der häufigste
Fehlerfall der automatischen Vorsortierung.

Findet die Suche keine Stelle oberhalb der Schwelle, ist der Status N — ohne
LLM-Aufruf. Das ist die Belegpflicht (Codebook R1).
"""

import inspect
import json
import re
from pathlib import Path
from typing import NamedTuple

import numpy as np
import ollama

from src.dokumente.vector_store import MODELL_NAME, einbetten, normalize_rows
from src.verzeichnisse import DATA_DIR as _DATA_DIR, STRUKTUR_NAME

DATA_DIR      = _DATA_DIR
STRUKTUR_FILE = DATA_DIR / STRUKTUR_NAME
STANDARD_FILE = DATA_DIR / "Standard_Lastenheft_Chunks.jsonl"

# Das Standardmodell, auf das Prompt und Schwellen abgestimmt sind. Hier steht
# der einzige Vorgabewert im Projekt — CLI und Oberfläche beziehen ihn von hier.
# Ein Vorgabewert, der von der abgestimmten Konfiguration abweicht, macht die
# berichtete Trefferquote zu einer Aussage über etwas anderes als das Werkzeug.
STANDARD_MODELL = "qwen3.5:9b"

# Zahl der Fundstellen aus dem geprüften Lastenheft, die je Kriterium in den
# Prompt gehen. Der wirksamste Hebel nach der Temperatur: Mehr Stellen heben den
# Recall, ohne die Precision zu verdünnen, bis das Kontextfenster die Grenze setzt.
N_FUNDSTELLEN = 30

# Obergrenze für die mitwachsende Fundstellenzahl: das, was das Kontextfenster
# hergibt. Darüber schneidet Ollama den Prompt stillschweigend von vorn ab —
# also genau dort, wo die Standardanforderung steht.
N_FUNDSTELLEN_MAX = 45

# Wie viele Abschnitte darf ein Dokument je Fundstellenplatz haben, bevor
# aufgestockt wird? Der Wert greift nur bei sehr langen Dokumenten. Anlass: Bei
# fester Platzzahl sieht ein sehr langes Dokument nur einen kleinen Bruchteil
# seiner Stellen, und die Belegstelle fehlt dort überproportional oft im
# Kandidatensatz. Es ist kein Vokabular-, sondern ein Längenproblem.
ABSCHNITTE_JE_PLATZ = 15


def fundstellen_zahl(anzahl_abschnitte: int,
                     vorgabe: int = N_FUNDSTELLEN) -> int:
    """Wie viele Kandidatenplätze bekommt ein Dokument dieser Länge?

    Kurze und mittlere Dokumente behalten die Standardzahl — dort ändert sich
    nichts. Nur sehr
    lange Dokumente stocken auf, bis zur Grenze des Kontextfensters.
    """
    return max(vorgabe, min(N_FUNDSTELLEN_MAX,
                            anzahl_abschnitte // ABSCHNITTE_JE_PLATZ))


# Ab welcher Ähnlichkeit eine Textstelle als Fundstelle in Frage kommt.
#
# Bei der gewählten Fundstellenzahl ist dieser Wert praktisch wirkungslos —
# und genau deshalb steht er hier und nicht als Regler in der Oberfläche.
# Unterhalb ändert sich nichts, oberhalb bricht es ein: Viele geregelte
# Kriterien bekämen gar keine Fundstelle mehr und stünden auf N — die Ausgabe
# sähe aus, als regele der Kunde fast nichts, und wäre plausibel und falsch
# zugleich. Über die CLI bleibt der Wert erreichbar (--min-score).
MIN_SCORE = 0.30

STATUS_WERTE = ("E", "T", "A", "N")
STATUS_TEXT  = {"E": "entspricht", "T": "teilweise",
                "A": "Abweichung", "N": "keine Vorgabe"}
EINSTUFUNGEN = ("Pflicht", "Regel", "Optional")


# ── Gliederung und Standard ───────────────────────────────────────────────────
def load_kriterien(path: Path | None = None) -> list[dict]:
    """Lädt die verbindliche Gliederung. Reihenfolge und Nummern sind stabile IDs."""
    data = json.loads((path or STRUKTUR_FILE).read_text(encoding="utf-8"))
    return data["kriterien"]


def load_standard(path: Path | None = None) -> dict[str, dict]:
    """Lädt die Standard-Chunks als {abschnitt_nr: chunk}.

    Fehlt die Datei, wird leer zurückgegeben — die Prüfung läuft dann ohne
    Vergleichsmaßstab und kann faktisch nur noch feststellen, OB ein Punkt
    geregelt ist, nicht ob abweichend.
    """
    p = path or STANDARD_FILE
    if not p.exists():
        return {}
    chunks = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = json.loads(line)
            chunks[c["abschnitt_nr"]] = c
    return chunks


def gliederung_als_text(kriterien: list[dict]) -> str:
    """Rendert die Gliederung als nummerierte Klartextliste für den Prompt.

    Wird aus der JSON erzeugt, damit Struktur und Prompt nicht doppelt gepflegt
    werden müssen.
    """
    lines: list[str] = []
    kapitel_nr = 0
    letztes_kapitel = None
    for k in kriterien:
        if k["kapitel"] != letztes_kapitel:
            kapitel_nr += 1
            letztes_kapitel = k["kapitel"]
            if lines:
                lines.append("")
            lines.append(f"{kapitel_nr} {k['kapitel']}")
        lines.append(f"  {k['nr']}  {k['titel']}  [{k['einstufung']}]")
    return "\n".join(lines)


# ── Prompt-Bausteine ──────────────────────────────────────────────────────────
# Wörtlich aus der Agenten-Instruktion.
# Der Regelteil lebt in promptprofil.py.
from src.pruefung.promptprofil import regeln
from src.pruefung import beispiele as beispiele_modul
from src.pruefung import herkunft
from src.pruefung import steckbrief
from src.muster import anwendungsfeld

REGELN = regeln()


# Der vollständige Agenten-Auftrag — die vertragliche Beschreibung der Aufgabe.
# {gliederung} wird zur Laufzeit aus struktur_kriterien.json gefüllt.
# @@REGELN@@ ist der Platzhalter für den Regelteil und wird nicht über .format()
# gefüllt, sondern per replace(): Der Regeltext enthält geschweifte Klammern in
# Beispielen, und .format() würde darüber stolpern.
_AGENT_VORLAGE = """Du prüfst ein eingehendes Kundenlastenheft für ein Druckgießwerkzeug gegen einen
Standard, der aus 18 historischen Lastenheften abgeleitet wurde.

## Verbindliche Gliederung

Du bewertest genau die folgenden 67 Kriterien, in dieser Reihenfolge, unter diesen
Nummern. Du erfindest keine eigenen Abschnitte, fasst keine zusammen und lässt keines
aus. Auch Kriterien, zu denen das Lastenheft nichts sagt, erscheinen in der Ausgabe —
mit Status N.

Die Angabe in eckigen Klammern ist die Verbreitung im Referenzkorpus. Sie beeinflusst
deine Bewertung nicht, sondern nur die spätere Gewichtung eines Befunds.

{gliederung}

@@REGELN@@

## Zusatzanforderungen

Kundenanforderungen ohne Entsprechung in den 67 Kriterien sammelst du getrennt in
zusatzanforderungen. Sie erzeugen kein zusätzliches Kriterium und gehen nicht in die
Kennzahlen ein.

## Ausgabeformat

Gib ausschließlich ein JSON-Objekt in genau dieser Form zurück, ohne umgebenden Text:

{{
  "lh_id": "<Kennung des geprüften Lastenhefts>",
  "bewertungen": {{
    "1.1": {{"status": "E", "begruendung": "<ein Satz>", "fundstelle": "S3"}},
    "1.2": {{"status": "N", "begruendung": "", "fundstelle": ""}}
  }},
  "zusatzanforderungen": ["<Anforderung> (S<Seite>)"]
}}

bewertungen enthält alle 67 Nummern der Gliederung. Bei Status N sind begruendung und
fundstelle leere Zeichenketten. Kennzahlen berechnest du nicht selbst."""


# Prompt für einen einzelnen Durchgang der Kriterien-Schleife.
_KRITERIUM_VORLAGE = """Du prüfst ein eingehendes Kundenlastenheft für ein Druckgießwerkzeug gegen einen
Standard, der aus 18 historischen Lastenheften abgeleitet wurde.

In diesem Durchgang bewertest du GENAU EIN Kriterium der verbindlichen Gliederung:

KRITERIUM {nr} — {titel}
Kapitel: {kapitel}

{standard}

STELLEN AUS DEM GEPRÜFTEN LASTENHEFT (Kandidaten, nach Ähnlichkeit sortiert):
{fundstellen}

@@REGELN@@

## Ausgabeformat

Gib ausschließlich ein JSON-Objekt zurück, ohne umgebenden Text und ohne Codeblock:

{{"status": "E", "begruendung": "<ein Satz>", "fundstelle": "S3"}}

status ist genau einer von E, T, A, N. fundstelle ist die Seitenangabe der Kandidaten-
stelle, auf die du dich stützt, im Format S<Seite>. Bei Status N sind begruendung und
fundstelle leere Zeichenketten. Bewerte ausschließlich Kriterium {nr}."""


# Dieselben Bausteine, nur der Regelteil steht VOR dem Kriterium statt hinter
# den Fundstellen. Inhaltlich Zeichen für Zeichen dieselben Blöcke — ein Test
# sichert das ab.
#
# Der Grund ist die Laufzeit, nicht die Güte: Ollama rechnet beim nächsten Prompt
# nur den Teil neu, der sich vom gemeinsamen Anfang unterscheidet.
#
# Erprobt und verworfen: deutlich schlechtere Trefferquote bei nur geringer
# Zeitersparnis. Der Schalter bleibt aus.
_KRITERIUM_VORLAGE_REGELN_VORAN = """Du prüfst ein eingehendes Kundenlastenheft für ein Druckgießwerkzeug gegen einen
Standard, der aus 18 historischen Lastenheften abgeleitet wurde.

@@REGELN@@

In diesem Durchgang bewertest du GENAU EIN Kriterium der verbindlichen Gliederung:

KRITERIUM {nr} — {titel}
Kapitel: {kapitel}

{standard}

STELLEN AUS DEM GEPRÜFTEN LASTENHEFT (Kandidaten, nach Ähnlichkeit sortiert):
{fundstellen}

## Ausgabeformat

Gib ausschließlich ein JSON-Objekt zurück, ohne umgebenden Text und ohne Codeblock:

{{"status": "E", "begruendung": "<ein Satz>", "fundstelle": "S3"}}

status ist genau einer von E, T, A, N. fundstelle ist die Seitenangabe der Kandidaten-
stelle, auf die du dich stützt, im Format S<Seite>. Bei Status N sind begruendung und
fundstelle leere Zeichenketten. Bewerte ausschließlich Kriterium {nr}."""


# Schritt 1 des Regelteils als eigenes Antwortfeld, VOR dem Status.
#
# Anlass: Ein großer Teil der Fälle, in denen das Modell „keine Vorgabe" sagt,
# obwohl der Kunde regelt, sind Urteilsfehler — die Stelle lag vor. Statt eines
# weiteren Regelsatzes eine Änderung am Antwortformat: Die Frage muss
# beantwortet werden, bevor der Status fällt. Der Parser ignoriert das Feld —
# es wirkt allein dadurch, dass es ausgefüllt wird.
_AUSGABE_OHNE = '''{{"status": "E", "begruendung": "<ein Satz>", "fundstelle": "S3"}}

status ist genau einer von E, T, A, N.'''

_AUSGABE_MIT_BERUEHRT = '''{{"beruehrt": true, "status": "E", "begruendung": "<ein Satz>", "fundstelle": "S3"}}

beruehrt beantwortet Schritt 1 und steht bewusst VOR dem Status: Wird der
Sachverhalt des Kriteriums in einer der gezeigten Stellen berührt — gleich ob
vollständig, verbindlich oder nur nebenbei? Beantworte diese Frage zuerst und
erst danach den Status. Nur bei beruehrt = false ist status N.

status ist genau einer von E, T, A, N.'''


def kriterium_prompt(hinausgehen: bool = False,
                     listenpunkte: bool = False,
                     einschraenkung: bool = False,
                     beispiele: list | None = None,
                     beruehrt_feld: bool = False,
                     verschaerfung: bool = False,
                     feld: "anwendungsfeld.Anwendungsfeld | None" = None,
                     neutrales_beispiel: bool = False,
                     fabrikat_ist_abweichung: bool = False,
                     regeln_voran: bool = False) -> str:
    """Die Vorlage für einen Schleifendurchgang, mit dem Regelteil. Noch
    offen: {nr}, {titel}, {kapitel}, {standard},
    {fundstellen}.

    `beispiele` sind Paare (Lage, Begründung), die als Abweichungsbeispiele
    hinter den Regelteil treten — siehe src/pruefung/beispiele.py. None oder leer heißt:
    kein Block, der Prompt bleibt Zeichen für Zeichen der bisherige.

    `beruehrt_feld` verlangt Schritt 1 als eigenes Antwortfeld, siehe oben.

    `feld` ist das Anwendungsfeld des Standards (src/muster/anwendungsfeld.py). None
    heißt: das des hinterlegten Musterlastenhefts.

    `regeln_voran` stellt den Regelteil vor das Kriterium, damit Ollama ihn
    zwischen den 67 Aufrufen nicht neu auswertet — siehe
    _KRITERIUM_VORLAGE_REGELN_VORAN.
    """
    feld = feld or anwendungsfeld.aktuell()
    vorlage = _KRITERIUM_VORLAGE_REGELN_VORAN if regeln_voran else _KRITERIUM_VORLAGE
    text = vorlage.replace(
        "@@REGELN@@", regeln(hinausgehen, listenpunkte, einschraenkung,
                             verschaerfung, feld=feld,
                             fabrikat_ist_abweichung=fabrikat_ist_abweichung))
    block = beispiele_modul.block(beispiele or [])
    if block:
        # Vor das Ausgabeformat, damit die Form der Antwort zuletzt steht.
        text = text.replace("\n## Ausgabeformat", f"\n{block}\n## Ausgabeformat")
    if beruehrt_feld:
        assert _AUSGABE_OHNE in text, "Ausgabeformat geändert — Schalter anpassen"
        text = text.replace(_AUSGABE_OHNE, _AUSGABE_MIT_BERUEHRT, 1)
    if neutrales_beispiel:
        # Das Formatbeispiel nannte `"status": "E"` — der Verdacht: Das Modell
        # übernimmt den Beispielwert. Platzhalter statt Wert.
        alt = '{{"status": "E", "begruendung": "<ein Satz>", "fundstelle": "S3"}}'
        assert text.count(alt) >= 1, "Ausgabeformat geändert — Schalter anpassen"
        text = text.replace(
            alt, '{{"status": "<E, T, A oder N>", "begruendung": "<ein Satz>", '
                 '"fundstelle": "S<Seite>"}}')
    return anwendungsfeld.uebertragen(text, feld, format_sicher=True)


def agent_prompt(feld: "anwendungsfeld.Anwendungsfeld | None" = None,
                 anzahl: int | None = None) -> str:
    """Der vollständige Auftrag, wie ihn die Oberfläche zum Nachlesen zeigt.
    Noch offen: {gliederung}."""
    feld = feld or anwendungsfeld.aktuell()
    anzahl = anzahl if anzahl is not None else anwendungsfeld.anzahl_kriterien()
    return anwendungsfeld.uebertragen(
        _AGENT_VORLAGE.replace("@@REGELN@@", regeln(feld=feld)),
        feld, anzahl, format_sicher=True)


# Für die Aufrufer, die keine Schalter setzen.
KRITERIUM_PROMPT = kriterium_prompt()
AGENT_PROMPT = agent_prompt()


ZUSATZ_PROMPT = """Du prüfst ein Kundenlastenheft für ein Druckgießwerkzeug gegen eine feste Gliederung
aus 67 Kriterien. Die folgenden Abschnitte des Lastenhefts ließen sich keinem dieser
Kriterien zuordnen.

ABSCHNITTE:
{abschnitte}

Extrahiere daraus die eigenständigen Kundenanforderungen — also Vorgaben, die der
Auftragnehmer erfüllen muss. Verwirf Inhaltsverzeichnisse, Kopf- und Fußzeilen,
Verzeichnisse, Adressblöcke und reinen Fließtext ohne Anforderungscharakter.

Gib ausschließlich ein JSON-Array zurück, ohne umgebenden Text:

["<Anforderung in einem Satz> (S<Seite>)", "<Anforderung> (S<Seite>)"]

Findest du keine echte Zusatzanforderung, gib [] zurück."""


# ── LLM-Hilfen ────────────────────────────────────────────────────────────────
# Ollama allokiert das Kontextfenster standardmäßig mit nur 4096 Tokens,
# unabhängig davon, was das Modell könnte. Ein Kriteriums-Prompt liegt bei
# 2400–2700 Tokens; bei längeren Belegstellen läuft er über — und dann kürzt
# Ollama ihn STILLSCHWEIGEND VON VORN, also genau dort, wo die Standard-
# anforderung steht. Deshalb explizit Luft schaffen.
NUM_CTX = 8192

# Nur ein Mini-JSON wird gebraucht. Die Obergrenze wirkt zugleich als Bremse,
# falls ein Reasoning-Modell sein Denken nicht beendet.
NUM_PREDICT = 512

# Die Einstufung eines Kriteriums ist eine Beurteilung, keine Textproduktion —
# Zufall hat hier keinen Nutzen. Fester Seed zusätzlich, weil manche Backends
# auch bei Temperatur 0 nicht vollständig deterministisch sind.
TEMPERATURE = 0.0
SEED = 42

# `think` gibt es erst ab ollama-python 0.5. Einmal prüfen statt bei jedem Aufruf.
_THINK_SUPPORTED = "think" in inspect.signature(ollama.chat).parameters


class LLMAntwort(NamedTuple):
    """Ergebnis eines LLM-Aufrufs.

    `ok=False` heißt: das Modell hat nicht verwertbar geantwortet. Das ist etwas
    anderes als „der Kunde regelt diesen Punkt nicht" und darf nicht als N
    durchgereicht werden, ohne es zu melden.
    """
    text:  str
    ok:    bool
    grund: str
    # Wahrscheinlichkeiten der vier Statuswerte an der Stelle, an der das Modell
    # den Status schreibt — nur wenn ausdrücklich angefordert und lokal.
    status_p: dict | None = None


_STATUSWERTE = ("E", "T", "A", "N")

# Präfix des Grunds, wenn der Aufruf selbst scheitert — Ollama nicht erreichbar,
# Modell nicht geladen. Erkannt von ist_verbindungsfehler().
VERBINDUNGSFEHLER = "LLM-Aufruf fehlgeschlagen"

# Nach so vielen Verbindungsfehlern in Folge wird der Rest des Laufs nicht mehr
# angefragt. Anlass: Bei ausgeschaltetem Ollama liefen alle Aufrufe nacheinander
# ins Leere, und das Ergebnis sah aus wie ein Lauf mit lauter „keine Vorgabe".
# Der Zähler steht im Ergebnis (`nicht_bewertet`), und der Lauf hört auf,
# sobald klar ist, dass niemand antwortet.
MAX_VERBINDUNGSFEHLER_IN_FOLGE = 3


def ist_verbindungsfehler(grund: str) -> bool:
    return "aufruf fehlgeschlagen" in (grund or "").lower()


def _status_verteilung(logprobs) -> dict | None:
    """Wahrscheinlichkeit von E/T/A/N am Status-Token der JSON-Antwort.

    Das Modell schreibt `{"status": "E", …}`; der Buchstabe ist ein eigenes
    Token, und Ollama liefert dort die wahrscheinlichsten Alternativen mit.
    Normiert wird über die vier Statuswerte — andere Alternativen („S", Leerzeichen)
    haben am Status-Token praktisch keine Masse.
    """
    import math

    bisher = ""
    for eintrag in logprobs or []:
        d = eintrag if isinstance(eintrag, dict) else eintrag.model_dump()
        token = d.get("token") or ""
        if token.strip() in _STATUSWERTE and re.search(r'"status"\s*:\s*"$', bisher):
            p = {s: 0.0 for s in _STATUSWERTE}
            for alt in d.get("top_logprobs") or []:
                s = (alt.get("token") or "").strip()
                if s in p:
                    p[s] = max(p[s], math.exp(alt.get("logprob", -99)))
            summe = sum(p.values())
            return {s: round(v / summe, 4) for s, v in p.items()} if summe else None
        bisher += token
    return None


def _chat(model: str, prompt: str, num_predict: int = NUM_PREDICT,
          num_ctx: int = NUM_CTX,
          mit_statuswahrscheinlichkeit: bool = False) -> LLMAntwort:
    """Ein LLM-Aufruf über das lokale Ollama. Gibt den Antworttext ohne <think>-Block zurück."""
    kwargs = {"options": {
        "num_predict": num_predict,
        "num_ctx":     num_ctx,
        # Reproduzierbarkeit. Ohne feste Temperatur kippten zwei Läufe mit
        # identischem Prompt für dasselbe Dokument um elf Kriterien an der
        # E/T-Grenze — damit ist kein A/B-Vergleich interpretierbar, und für eine
        # wissenschaftliche Arbeit ist Wiederholbarkeit ohnehin Voraussetzung.
        "temperature": TEMPERATURE,
        "seed":        SEED,
    }}
    if _THINK_SUPPORTED:
        # Für ein Mini-JSON ist Reasoning reine Laufzeit und liefert oft leere Antworten.
        kwargs["think"] = False
    if mit_statuswahrscheinlichkeit:
        kwargs["logprobs"] = True
        kwargs["top_logprobs"] = 10

    try:
        response = ollama.chat(model=model, messages=[{"role": "user", "content": prompt}],
                               **kwargs)
    except Exception as e:
        return LLMAntwort("", False, f"{VERBINDUNGSFEHLER}: {e}")

    msg     = response["message"]
    content = msg.get("content") or ""
    text    = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    if not text:
        denk = len(msg.get("thinking") or "")
        if response.get("done_reason") == "length" and denk:
            hinweis = ("Das Denken lässt sich hier nicht abschalten: ollama-python ist "
                       "zu alt (>=0.5 nötig). Danach Streamlit neu starten."
                       if not _THINK_SUPPORTED else
                       "Denken war abgeschaltet und das Modell hat trotzdem gedacht — "
                       "num_predict erhöhen.")
            return LLMAntwort("", False, (
                f"Reasoning-Modell hat das Token-Budget im Denkblock verbraucht "
                f"({denk} Zeichen Denken, Antwort leer). Mehr Kontext hilft nicht — "
                f"das Modell denkt dann nur proportional länger. {hinweis} "
                f"Alternative: ein Modell ohne Reasoning, z.B. qwen2.5:7b."))
        if response.get("done_reason") == "length":
            return LLMAntwort("", False,
                              f"Antwort nach {num_predict} Tokens abgeschnitten, ohne "
                              f"verwertbaren Inhalt. num_predict erhöhen.")
        return LLMAntwort("", False,
                          f"Modell lieferte keinen Antworttext ({denk} Zeichen Denkblock).")

    status_p = None
    if mit_statuswahrscheinlichkeit:
        lp = response.get("logprobs") if isinstance(response, dict) \
            else getattr(response, "logprobs", None)
        status_p = _status_verteilung(lp)
    return LLMAntwort(text, True, "", status_p)


def _first_json(text: str, opener: str = "{") -> str | None:
    """Schneidet das erste balancierte JSON-Objekt/-Array aus einem Antworttext.

    Lokale Modelle rahmen JSON gern mit Codefences oder Vorrede ein, trotz
    gegenteiliger Anweisung.
    """
    closer = "}" if opener == "{" else "]"
    start = text.find(opener)
    if start == -1:
        return None
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


ANTWORT_UNLESBAR = "Antwort nicht lesbar"


def _gelesene_bewertung(text: str) -> dict | None:
    """Die Bewertung aus der LLM-Antwort — oder None, wenn sie nicht lesbar ist.

    Lesbar heißt: ein JSON-Objekt mit einem zulässigen Status. Früher gab es
    einen Rückfall, der ein nacktes „status: A" irgendwo in Prosa suchte und die
    ersten Zeichen als Begründung nahm. So wurde aus Prosa ein Urteil mit der
    Seite des besten Kandidaten — die Belegpflicht griff
    nicht, weil eine Begründung dastand. Ein Urteil aus einer unlesbaren Antwort
    ist keins; der Fall zählt jetzt als Werkzeugausfall (`nicht_bewertete()`).
    """
    blob = _first_json(text)
    if not blob:
        return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    status = str(data.get("status", "")).strip().upper()[:1]
    if status not in STATUS_WERTE:
        return None
    if status == "N":
        return {"status": "N", "begruendung": "", "fundstelle": ""}
    return {
        "status":      status,
        "begruendung": str(data.get("begruendung", "")).strip(),
        "fundstelle":  str(data.get("fundstelle", "")).strip(),
    }


def _parse_bewertung(text: str) -> dict:
    """Wandelt die LLM-Antwort in {status, begruendung, fundstelle}.

    Unparsbare oder unzulässige Antworten werden zu N degradiert statt zu raten —
    ein erfundener Status wäre schlimmer als eine fehlende Vorgabe. Wer wissen
    muss, OB die Antwort lesbar war, nimmt `_gelesene_bewertung`.
    """
    return _gelesene_bewertung(text) or {"status": "N", "begruendung": "", "fundstelle": ""}


def _erzwinge_belegpflicht(bewertung: dict, kandidaten: list[dict]) -> dict:
    """Setzt Codebook-Regel R1 durch: E/T/A ohne Beleg wird zu N.

    Fehlt nur die Seitenangabe, während eine Begründung vorliegt, wird die Seite
    des besten Kandidaten eingesetzt — die Stelle existiert dann ja.

    Dasselbe gilt für eine Seite, die unter den vorgelegten Stellen gar nicht
    vorkommt. Vorher genügte irgendeine Ziffer, und eine vom Modell erfundene „S97“
    stand als Beleg im Bericht. Genannt das Modell mehrere Seiten, bleiben die
    vorgelegten; ist keine davon vorgelegt, gilt die Seite des besten Kandidaten.
    """
    if bewertung["status"] == "N":
        return {"status": "N", "begruendung": "", "fundstelle": ""}

    if not bewertung["begruendung"]:
        return {"status": "N", "begruendung": "", "fundstelle": ""}

    if not kandidaten:
        if not re.search(r"\d", bewertung["fundstelle"]):
            return {"status": "N", "begruendung": "", "fundstelle": ""}
        return bewertung

    vorgelegt = {str(k["page"]) for k in kandidaten}
    genannt = _SEITENZAHL.findall(bewertung["fundstelle"])
    belegt = list(dict.fromkeys(s for s in genannt if s in vorgelegt))
    if not belegt:
        bewertung["fundstelle"] = f"S{kandidaten[0]['page']}"
    elif len(belegt) < len(genannt):
        bewertung["fundstelle"] = ", ".join(f"S{s}" for s in belegt)
    return bewertung


# Seitenzahlen in einer Fundstellenangabe: „S3“, „S. 3“, „Seite 3“, „S3, S7“, „3“.
# Gliederungsnummern („Abschnitt 4.2“) sind keine Seiten und bleiben außen vor.
_SEITENZAHL = re.compile(r"(?<![\d.,])(\d{1,4})(?![\d]|[.,]\d)")


# ── Aussortieren von Verzeichnissen und Kopf-/Fußzeilen (Codebook R2) ─────────
_VERZEICHNIS_TITEL = re.compile(
    r"\b(inhalts?verzeichnis|inhalt|table of contents|abbildungsverzeichnis|"
    r"tabellenverzeichnis|abkürzungsverzeichnis|revisionshistorie)\b", re.IGNORECASE)

# "3.4 Toleranzauslegung ......... 12"  oder  "3.4 Toleranzauslegung   12"
_TOC_ZEILE = re.compile(r"^\s*\d+(\.\d+)*\.?\s+\S.{0,80}?(\.{3,}|\s{3,}|\t)\s*\d{1,3}\s*$")


# Steht eines dieser Wörter vor dem Titelwort, ist es Teil eines Satzes:
# „Im Inhaltsverzeichnis sind sämtliche Zeichnungen …", „Protokolle mit
# folgendem Inhalt". Solche Anforderungen dürfen nicht als Verzeichnis
# ausgesondert werden.
_SATZWORT_DAVOR = frozenset(
    "im in das des der die dem den mit und was zum zur vom am auf für über ohne "
    "eines einer einem ein eine folgendem folgenden folgender ihrem ihren seinem "
    "seinen deren dessen of the with and".split())

# Erprobt und verworfen: Abschnitte mit mehreren Punktreihen als Verzeichnis
# aussondern. Das traf auch Stücklisten und Formblätter mit Punktführung, auf
# denen Kriterien belegt sind. Der Filter bleibt beim Titelwort.


def ist_verzeichnis(text: str) -> bool:
    """Erkennt Inhalts- und andere Verzeichnisse.

    Laut Briefing der häufigste Fehlerfall: im Inhaltsverzeichnis kommt jedes
    Stichwort vor, geregelt ist dort nichts.

    Ein Verzeichnistitel in den ersten 120 Zeichen zählt nur, wenn er nicht Teil
    eines Satzes ist — sonst fielen echte Anforderungen aus der Suche.
    """
    kopf = text[:120]
    for m in _VERZEICHNIS_TITEL.finditer(kopf):
        davor = kopf[:m.start()].split()
        if davor and davor[-1].lower().strip(".,;:()") in _SATZWORT_DAVOR:
            continue
        # Das bloße Wort „Inhalt" zählt nur ganz am Anfang; mitten im Text ist
        # es fast immer ein Satz („… und was Inhalt der Beschriftung sein muss").
        if m.group(1).lower() == "inhalt" and davor:
            continue
        return True
    zeilen = [z for z in text.split("\n") if z.strip()]
    if len(zeilen) < 2:
        # Einzeiler mit Punktführung ist ebenfalls eine Verzeichniszeile
        return bool(zeilen) and bool(_TOC_ZEILE.match(zeilen[0]))
    treffer = sum(1 for z in zeilen if _TOC_ZEILE.match(z))
    return treffer / len(zeilen) >= 0.5


def _kriterium_query(kriterium: dict, standard: dict | None) -> str:
    """Suchtext für ein Kriterium — bevorzugt den vorbereiteten embedding_text."""
    if standard and standard.get("embedding_text"):
        return standard["embedding_text"]
    begriffe = ", ".join(kriterium.get("abgleichbegriffe", []))
    return f"{kriterium['titel']}. {begriffe}" if begriffe else kriterium["titel"]


# Begriffe bis zu dieser Länge werden nur als ganzes Wort gesucht. Als
# Teilzeichenkette träfen kurze Kürzel („Ra" aus „Rahmen") fast jeden Abschnitt
# und verfälschten Relevanzschwelle und Entscheider-Merkmale. Längere Begriffe
# bleiben Teilzeichenketten: „Kern" soll „Kernzug" treffen.
_KURZER_BEGRIFF = 3
_kurz_muster: dict[str, re.Pattern] = {}


# Englische Lastenhefte trifft der Wortvergleich mit deutschen Abgleichbegriffen
# nicht. Die Übersetzungen stehen in einer eigenen Datei neben diesem Modul —
# versioniert, weil sie nur Fachbegriffe und Kriterientitel enthält. Sie gehen nur
# in die Suche ein, nicht in den Prompt. Ein Eintrag gilt nur, wenn sein Titel zum
# Kriterium passt — ein anderes Musterlastenheft mit anderer Gliederung bekommt
# keine falschen Begriffe.
ENGLISCHE_BEGRIFFE = True
_EN_DATEI = Path(__file__).with_name("abgleichbegriffe_en.json")
_en_cache: dict | None = None


def englische_abgleichbegriffe(kriterium: dict) -> list[str]:
    global _en_cache
    if _en_cache is None:
        try:
            _en_cache = json.loads(_EN_DATEI.read_text(encoding="utf-8")).get("kriterien", {})
        except (OSError, json.JSONDecodeError):
            _en_cache = {}
    eintrag = _en_cache.get(kriterium.get("nr")) or {}
    if eintrag.get("titel") != kriterium.get("titel"):
        return []
    return list(eintrag.get("begriffe") or [])


def _lexikalischer_score(text_lower: str, begriffe: list[str]) -> float:
    """Anteil der Abgleichbegriffe, die im Abschnitt vorkommen (0.0–1.0).

    Lexikalische Ergänzung zur semantischen Suche: Lastenhefte benennen denselben
    Sachverhalt sehr unterschiedlich, Normbezeichnungen wie "DIN 1530" trifft ein
    Embedding-Modell schlechter als ein Substring-Vergleich.
    """
    if not begriffe:
        return 0.0
    treffer = 0
    for b in begriffe:
        bl = b.lower()
        if len(bl) <= _KURZER_BEGRIFF:
            muster = _kurz_muster.get(bl)
            if muster is None:
                muster = _kurz_muster[bl] = re.compile(
                    r"(?<![0-9a-zäöüß])" + re.escape(bl) + r"(?![0-9a-zäöüß])")
            if muster.search(text_lower):
                treffer += 1
        elif bl in text_lower:
            treffer += 1
    # Drei Treffer gelten als voller lexikalischer Beleg.
    return min(treffer / 3.0, 1.0)


# Platzhalter, die auf ein Erzeugnis zielen — Typ, Fabrikat, Hersteller,
# Lieferant, Artikel. Der Standard führt sie als Variable und lässt die Wahl
# damit ausdrücklich offen; genau darauf stützt sich R5 der Ground Truth
# („Fabrikatsbindung ist Abweichung, weil der Standard herstellerneutral
# formuliert ist").
#
# Das Merkmal wird ALLEIN aus dem Feld `platzhalter` des Standards abgeleitet,
# nicht daraus, wo im Referenzkorpus Abweichungen liegen. Sonst wäre es an den
# Testfällen angepasst und die Messung wertlos.
_TYP_PLATZHALTER = re.compile(
    r"typ|fabrikat|hersteller|lieferant|marke|artikel", re.I)


def typ_platzhalter(chunk: dict | None) -> list[str]:
    """Die Platzhalter eines Kriteriums, die ein Erzeugnis offenlassen."""
    if not chunk:
        return []
    return [p for p in chunk.get("platzhalter", [])
            if _TYP_PLATZHALTER.search(p)]


# Ersatz-Platzhalter für Zukaufteil-Kriterien ohne eigenen Typ-Platzhalter.
ZUKAUFTEIL_PLATZHALTER = "Fabrikat und Typ der Zukaufteile"


def erzeugnis_platzhalter(kriterium: dict, chunk: dict | None,
                          weit: bool = False) -> list[str]:
    """Die offene Erzeugniswahl eines Kriteriums — eng oder weit gefasst.

    Eng (bisher) nur aus dem Feld `platzhalter`. Damit fehlten Kriterien für
    Zukaufteile, in denen Fabrikatsbindungen häufig sind.

    Weit kommen die Kriterien dazu, deren Titel ein Zukaufteil nennt — dieselbe
    Liste wie in src/pruefung/markenvorgabe.py, also ohne Blick auf die Referenz.
    """
    typ_ph = typ_platzhalter(chunk)
    if typ_ph or not weit or not chunk:
        return typ_ph
    from src.pruefung.markenvorgabe import ZUKAUFTEIL_TITEL
    titel = chunk.get("abschnitt_titel") or kriterium.get("titel", "")
    return [ZUKAUFTEIL_PLATZHALTER] if ZUKAUFTEIL_TITEL.search(titel) else []


def _format_standard(kriterium: dict, chunk: dict | None,
                     querverweise: str = "",
                     mit_fabrikatshinweis: bool = False,
                     erzeugnishinweis_weit: bool = False,
                     ohne_korpusbeispiele: bool = False,
                     feld: "anwendungsfeld.Anwendungsfeld | None" = None) -> str:
    """Rendert den Vergleichsmaßstab für den Prompt.

    `querverweise` wird angehängt statt über einen eigenen Prompt-Platzhalter
    geführt — so bleiben bearbeitete Prompt-Vorlagen ohne diesen Platzhalter
    weiterhin gültig.

    `mit_fabrikatshinweis` behebt einen Widerspruch zwischen Prompt und
    Regelwerk. Über ALLEN Platzhaltern stand „ein konkreter Wert dafür ist E,
    keine Abweichung" — auch über Typ- und Fabrikatsplatzhaltern. Für Zahlenwerte
    ist das richtig, für Erzeugnisse je nach Regelwerk das Gegenteil.
    """
    if not chunk:
        begriffe = ", ".join(kriterium.get("abgleichbegriffe", [])) or "—"
        return ("STANDARDANFORDERUNG: (kein Standard-Chunk hinterlegt — beurteile allein, "
                f"OB das Lastenheft den Punkt regelt)\nAbgleichbegriffe: {begriffe}"
                + querverweise)

    # Das Feld heißt aus historischen Gründen `belegt_in_n_von_18`; die Zahl
    # dahinter ist die Korpusgröße des jeweiligen Musterlastenhefts.
    feld   = feld or anwendungsfeld.aktuell()
    belegt = chunk.get('belegt_in_n_von_18', '?')
    teile  = [f"STANDARDANFORDERUNG (Einstufung {chunk.get('einstufung', '—')}, "
              + (f"belegt in {belegt} von {feld.korpus_dativ}):" if feld.korpus
                 else f"belegt in {belegt} Lastenheften):")]
    for s in chunk.get("standardanforderungen", []):
        teile.append(f"- {s}")

    typ_ph = (erzeugnis_platzhalter(kriterium, chunk, erzeugnishinweis_weit)
              if mit_fabrikatshinweis else [])

    # `ohne_korpusbeispiele` lässt die Ausprägungen weg. Anlass: Das Modell gab in
    # Einzelfällen diesen Block wörtlich zurück, statt das Kundendokument zu lesen.
    # Erprobt und verworfen — ohne den Block findet das Modell eher weniger; die
    # Beispiele zeigen ihm, wie eine Bindung aussieht. Der Schalter bleibt aus.
    auspraegungen = [] if ohne_korpusbeispiele else chunk.get("auspraegungen_im_korpus") or []
    if auspraegungen:
        teile.append("\nBEKANNTE AUSPRÄGUNGEN IM KORPUS (Werte innerhalb dieser Spannweiten "
                     "sind branchenüblich und damit E, nicht A):")
        for a in auspraegungen:
            teile.append(f"- {a}")
        if typ_ph:
            # Sonst liest das Modell eine im Korpus vorgefundene Marke als
            # Freibrief. Die Ausprägungen sind eine Beobachtung, keine
            # Erlaubnis: Sie zeigen, DASS Kunden hier Fabrikate nennen.
            teile.append("  Achtung: Eine hier genannte Marke oder Typnummer belegt nur, "
                         "dass ein Kunde sie vorgeschrieben hat — sie macht eine "
                         "Fabrikatsbindung nicht zur Regel.")

    if chunk.get("platzhalter"):
        frei = [p for p in chunk["platzhalter"] if p not in typ_ph]
        if frei:
            teile.append("\nPLATZHALTER (variieren je Projekt; ein konkreter Wert dafür ist E, "
                         "keine Abweichung): " + ", ".join(frei))
    if typ_ph:
        teile.append(
            "\nOFFENE ERZEUGNISWAHL: Für " + ", ".join(typ_ph) +
            " macht der Standard bewusst KEINE Vorgabe — er nennt weder "
            "Fabrikat noch Hersteller noch Lieferant. Schreibt der Kunde "
            "hier ein bestimmtes Fabrikat, einen Typ oder einen Lieferanten "
            "verbindlich vor, ist das eine Fabrikatsbindung und damit A. "
            "Regelt er den Sachverhalt ohne solche Bindung, bleibt es E.")

    if chunk.get("abgleichbegriffe"):
        teile.append("\nAbgleichbegriffe: " + ", ".join(chunk["abgleichbegriffe"]))

    return "\n".join(teile) + querverweise


def _format_fundstellen(kandidaten: list[dict]) -> str:
    if not kandidaten:
        return "(keine)"
    return "\n\n---\n\n".join(
        f"[Seite {k['page']}, Relevanz {k['score'] * 100:.0f}%]\n{k['text']}"
        for k in kandidaten
    )


# Ab diesem Relevanzwert gilt eine Fundstelle als tragend.
STARK = 0.45


def _beleglage(kandidaten: list[dict]) -> str:
    """Beschreibt, WIE gut ein Kriterium belegt ist — nicht nur womit.

    Die Referenz vergibt T oft mit
    Begründungen wie „erscheint nur in Positionslisten, kein eigenes Kapitel".
    Das ist eine Aussage über das ganze Dokument, und der Agent sieht nur
    Ausschnitte. Die Verteilung der Fundstellen ist die einzige Spur davon, die
    sich ohne vollständige Lektüre berechnen lässt.

    Erprobt und verworfen: Das Signal trennt im Mittel, im Einzelfall nicht — und
    weil E viel häufiger ist als T, kostet es mehr, als es bringt. Wird über
    `evaluate_document(mit_beleglage=...)` geschaltet und ist standardmäßig aus.
    """
    if not kandidaten:
        return ""
    stark = [k for k in kandidaten if k["score"] >= STARK]
    seiten = sorted({k["page"] for k in kandidaten})
    zeile = (f"BELEGLAGE: {len(kandidaten)} Stellen über der Relevanzschwelle, "
             f"davon {len(stark)} mit hoher Relevanz (ab {STARK * 100:.0f} %), "
             f"verteilt über {len(seiten)} Seiten.")
    if not stark:
        zeile += (" Keine einzige Stelle ist deutlich einschlägig — der Punkt "
                  "wird im Dokument allenfalls am Rande behandelt.")
    elif len(stark) >= 3:
        zeile += (" Mehrere deutlich einschlägige Stellen — der Punkt ist im "
                  "Dokument ausgeführt.")
    return zeile + "\n\n"


def fundstellen_je_kriterium(
    new_chunks: list,
    kriterien: list[dict] | None = None,
    standard: dict[str, dict] | None = None,
    n_fundstellen: int = N_FUNDSTELLEN,
    min_score: float = MIN_SCORE,
    lexikalisches_gewicht: float = 0.35,
    verzeichnisse_ausschliessen: bool = True,
    # Wird, wenn übergeben, mit Kennwerten des Laufs gefüllt. Als Beiwerk
    # geführt statt als vierter Rückgabewert, damit vorhandene Aufrufer
    # unberührt bleiben.
    statistik: dict | None = None,
    # Englische Übersetzungen der Abgleichbegriffe im Wortvergleich
    # (src/pruefung/abgleichbegriffe_en.json). None heißt: Vorgabe ENGLISCHE_BEGRIFFE.
    englische_begriffe: bool | None = None,
) -> tuple[dict[str, list[dict]], list, np.ndarray]:
    """Sucht je Kriterium die besten Stellen im geprüften Lastenheft.

    Herausgelöst, weil zwei Funktionen dieselbe Suche brauchen: die Prüfung
    gegen das Musterlastenheft und der Abgleich mit früheren Lastenheften.
    Der zweite kommt ohne Sprachmodell aus und darf deshalb nicht den ganzen
    Prüflauf voraussetzen.

    Rückgabe: (Kandidaten je Kriteriumsnummer, verwendete Abschnitte,
    Kriterien-Vektoren für weitere Suchen).
    """
    kriterien = kriterien if kriterien is not None else load_kriterien()
    standard  = standard  if standard  is not None else load_standard()

    if verzeichnisse_ausschliessen:
        chunks = [c for c in new_chunks if not ist_verzeichnis(c.text)]
    else:
        chunks = list(new_chunks)

    if not chunks:
        return {k["nr"]: [] for k in kriterien}, [], np.empty((0, 0), dtype=np.float32)

    # Beides über den Zwischenspeicher: Die Kriterienabfragen sind bei jedem
    # Dokument dieselben, und ein erneut geprüftes Dokument braucht keine
    # zweite Einbettung (siehe src/dokumente/vector_store.py).
    doc_norm  = normalize_rows(einbetten([c.text for c in chunks]))
    doc_lower = [c.text.lower() for c in chunks]

    query_vecs = einbetten(
        [_kriterium_query(k, standard.get(k["nr"])) for k in kriterien])

    w_lex = lexikalisches_gewicht
    treffer: dict[str, list[dict]] = {}
    for kriterium, qvec in zip(kriterien, query_vecs):
        begriffe = (standard.get(kriterium["nr"]) or kriterium).get("abgleichbegriffe", [])
        if ENGLISCHE_BEGRIFFE if englische_begriffe is None else englische_begriffe:
            begriffe = list(begriffe) + englische_abgleichbegriffe(kriterium)
        q     = qvec / (np.linalg.norm(qvec) + 1e-10)
        cos   = doc_norm @ q
        lex   = np.array([_lexikalischer_score(t, begriffe) for t in doc_lower],
                         dtype=np.float32)
        score = (1 - w_lex) * cos + w_lex * lex

        if statistik is not None:
            statistik.setdefault("_cos_summe", 0.0)
            statistik["_cos_summe"] += float(cos.sum())
            statistik["_cos_anzahl"] = statistik.get("_cos_anzahl", 0) + len(cos)

        k     = min(n_fundstellen, len(score))
        order = np.argsort(score)[::-1][:k] if k else []
        treffer[kriterium["nr"]] = [
            {"text": chunks[j].text, "page": chunks[j].page,
             "score": float(score[j]), "cos": float(cos[j]), "lex": float(lex[j]),
             "chunk": int(j)}
            for j in order if score[j] >= min_score
        ]
    if statistik is not None and statistik.get("_cos_anzahl"):
        # Die mittlere Ähnlichkeit über ALLE Abschnitte und alle Kriterien.
        # Sagt vorher, wie zuverlässig die Suche in diesem Dokument arbeitet
        # (r = +0,71 über die 18 Korpusdokumente) — siehe src/pruefung/dokumentguete.py.
        statistik["mittlere_aehnlichkeit"] = (
            statistik.pop("_cos_summe") / statistik.pop("_cos_anzahl"))
    return treffer, chunks, query_vecs


# ── Hauptlauf ─────────────────────────────────────────────────────────────────
def evaluate_document(
    new_chunks: list,
    lh_id: str,
    model: str = STANDARD_MODELL,
    n_fundstellen: int = N_FUNDSTELLEN,
    min_score: float = MIN_SCORE,
    lexikalisches_gewicht: float = 0.35,
    num_predict: int = NUM_PREDICT,
    kriterien: list[dict] | None = None,
    standard: dict[str, dict] | None = None,
    prompt_template: str | None = None,
    mit_zusatzanforderungen: bool = True,
    verzeichnisse_ausschliessen: bool = True,
    # Kleiner, aber durchweg positiver Effekt — deshalb Vorgabe an.
    mit_querverweisen: bool = True,
    n_querverweise: int = 3,
    min_querverweis_score: float = 0.45,
    # Erprobt ohne Wirkung, kostet aber deutlich Laufzeit. Bleibt aus.
    mit_abweichungspass: bool = False,
    # Stellt dem Fundstellenblock eine Zeile über die Belegdichte voran.
    # Erprobt und verworfen: mehr T, dafür deutlich weniger richtige E.
    mit_beleglage: bool = False,
    # Zusätzlicher Durchgang auf den 18 Kriterien, in denen das Musterlastenheft
    # selbst offen formuliert. Liefert Hinweise, keine Urteile — der Status
    # bleibt unberührt und die Kennzahlen sind mit früheren Läufen vergleichbar.
    # Kostet 18 statt 67 Aufrufe, rund 40 s je Dokument. Siehe src/pruefung/hinweise.py.
    mit_hinweisen: bool = True,
    # Hinweis auf offene Erzeugniswahl: Für Typ- und Fabrikatsplatzhalter gilt
    # nicht automatisch „ein konkreter Wert ist E". Aus, solange eine
    # Fabrikatsbindung keine Abweichung ist; ältere Läufe setzen ihn zusammen mit
    # `fabrikat_ist_abweichung` auf True.
    mit_fabrikatshinweis: bool = False,
    # Älterer Regelteil: „Fabrikatsbindung -> A". Siehe promptprofil.ohne_fabrikatsbindung.
    fabrikat_ist_abweichung: bool = False,
    # Zweistufige Frage nach dem Gegenteil einer Standardanforderung (Zuständigkeit,
    # Erlaubnis). Mehrere Aufrufe je Kriterium — siehe src/pruefung/gegenteil.py.
    # Stufen, die das Anzeichen „Gegenteil“ nutzen, schalten ihn selbst ein.
    mit_gegenteil: bool = False,
    # Den Fabrikatshinweis auf alle Zukaufteil-Kriterien ausweiten. Erprobt und
    # verworfen: zu wenig zusätzliche Treffer.
    erzeugnishinweis_weit: bool = False,
    # Tauscht die Prüffrage in Schritt 2 des Regelteils: statt „widerspricht
    # es dem Standard?" die Frage „verlangt der Kunde etwas, das der Standard
    # nicht verlangt?". Erprobt und verworfen.
    hinausgehen: bool = False,
    # „Nimmt der Kunde eine Wahl vorweg, die der Standard offenlaesst?" Eng auf
    # die Erzeugniswahl begrenzt — anders als `hinausgehen`, das nach ALLEM
    # fragte und deshalb ueberall feuerte. Erprobt und verworfen.
    einschraenkung: bool = False,
    # Ein benannter Punkt auf einer Anforderungsliste gilt als Vorgabe. Vom
    # Auftraggeber so bestaetigt. Erprobt ohne messbaren Effekt.
    listenpunkte: bool = False,
    # Sagt im Rahmensatz, dass eine Mehrforderung eine Abweichung ist, auch ohne
    # Widerspruch. Erprobt und verworfen: Verschärfungen wurden dadurch nicht
    # erkannt, und die Trefferquote sank, weil richtige E verloren gingen. Ein
    # kleines Modell lässt sich über einen Rahmensatz nicht zu einem
    # Umfangsvergleich bringen.
    verschaerfung: bool = False,
    # Fundstellenplaetze an die Dokumentlaenge koppeln. Siehe fundstellen_zahl().
    skaliere_fundstellen: bool = False,
    # Wird, wenn übergeben, mit Kennwerten des Laufs gefüllt — derzeit der
    # mittleren Ähnlichkeit, aus der src/pruefung/dokumentguete.py ableitet, wie
    # zuverlässig die Suche in diesem Dokument arbeitet.
    statistik: dict | None = None,
    # Anwendungsfeld des Standards. None: das des hinterlegten
    # Musterlastenhefts, siehe src/muster/anwendungsfeld.py.
    feld: "anwendungsfeld.Anwendungsfeld | None" = None,
    # Wie großzügig nach der Prüfung zusätzlich auf A gehoben wird — lieber eine
    # Abweichung zu viel als eine übersehen. Siehe src/pruefung/markierung.py. „aus" ist
    # das reine Modellurteil.
    markierung: str = "gruendlich",
    # Schreibt je Kriterium die Wahrscheinlichkeiten von E/T/A/N mit, abgelesen
    # am Status-Token der Antwort. Kein zusätzlicher Aufruf. Stufen, die sie
    # brauchen („gruendlich"), schalten es selbst ein.
    mit_wahrscheinlichkeiten: bool = False,
    # Zweiter Blick auf jedes vom Modell vergebene N: wörtliches Zitat verlangen,
    # der Code prüft es gegen die Stellen. Erprobt und verworfen.
    mit_n_nachpruefung: bool = False,
    # N des Modells auf E/T heben, wenn der gelernte Entscheider aus den
    # Suchmerkmalen das für wahrscheinlicher hält — siehe src/pruefung/entscheider.py.
    # Ohne trainierten Entscheider zum hinterlegten Standard wirkungslos.
    mit_entscheider: bool = True,
    # Je Kriterium zwei bis drei bewertete Fälle aus anderen Lastenheften in den
    # Maßstab: Stelle, Status, Begründung der Referenz. Das geprüfte Dokument selbst
    # liefert nie ein Beispiel. Erprobt ohne messbaren Effekt.
    referenzbeispiele: bool = False,
    # Formatbeispiel ohne konkreten Status. Erprobt und verworfen.
    neutrales_beispiel: bool = False,
    # Regelteil vor dem Kriterium statt hinter den Fundstellen, damit Ollama
    # den gemeinsamen Anfang aller Prompts aus dem Cache nimmt. Erprobt und
    # verworfen.
    regeln_voran: bool = False,
    progress_callback=None,
) -> tuple[dict, dict]:
    """Prüft ein Lastenheft entlang der 67 Kriterien.

    Rückgabe: (ergebnis, details)
      ergebnis — das JSON-Objekt gemäß Briefing, inkl. berechneter Kennzahlen
      details  — je Kriteriumsnummer Kandidatenstellen und Rohantwort des Modells;
                 nur für die Berichtsdarstellung, nicht Teil der Ausgabe
    """
    kriterien = kriterien if kriterien is not None else load_kriterien()
    standard  = standard  if standard  is not None else load_standard()
    feld      = feld or anwendungsfeld.aktuell()
    from src.pruefung.markierung import BRAUCHT_WAHRSCHEINLICHKEIT
    mit_wahrscheinlichkeiten = mit_wahrscheinlichkeiten or markierung in BRAUCHT_WAHRSCHEINLICHKEIT
    from src.pruefung.markierung import BRAUCHT_GEGENTEIL
    mit_gegenteil = mit_gegenteil or markierung in BRAUCHT_GEGENTEIL
    template  = prompt_template or kriterium_prompt(
        hinausgehen, listenpunkte, einschraenkung,
        verschaerfung=verschaerfung, feld=feld, neutrales_beispiel=neutrales_beispiel,
        regeln_voran=regeln_voran, fabrikat_ist_abweichung=fabrikat_ist_abweichung)

    # Womit ist das entstanden? Steht neben dem Ergebnis, geht in keine Kennzahl
    # ein — siehe src/pruefung/steckbrief.py. Als Funktion, weil auch der
    # Frühausstieg bei leerem Dokument denselben Steckbrief tragen soll.
    def _steckbrief() -> dict:
        return steckbrief.erstelle(
            modell=model,
            standard=standard,
            prompt_template=template,
            schalter={
                "mit_querverweisen": mit_querverweisen,
                "mit_zusatzanforderungen": mit_zusatzanforderungen,
                "mit_hinweisen": mit_hinweisen,
                "verzeichnisse_ausschliessen": verzeichnisse_ausschliessen,
                "mit_abweichungspass": mit_abweichungspass,
                "mit_beleglage": mit_beleglage,
                "mit_fabrikatshinweis": mit_fabrikatshinweis,
                "erzeugnishinweis_weit": erzeugnishinweis_weit,
                "fabrikat_ist_abweichung": fabrikat_ist_abweichung,
                "mit_gegenteil": mit_gegenteil,
                "verschaerfung": verschaerfung,
                "hinausgehen": hinausgehen,
                "einschraenkung": einschraenkung,
                "listenpunkte": listenpunkte,
                "skaliere_fundstellen": skaliere_fundstellen,
                "mit_wahrscheinlichkeiten": mit_wahrscheinlichkeiten,
                "mit_n_nachpruefung": mit_n_nachpruefung,
                "neutrales_beispiel": neutrales_beispiel,
                "mit_entscheider": mit_entscheider,
                "referenzbeispiele": referenzbeispiele,
                "regeln_voran": regeln_voran,
            },
            n_fundstellen=n_fundstellen,
            min_score=min_score,
            lexikalisches_gewicht=lexikalisches_gewicht,
            abschnitte=len(new_chunks),
            einbettungsmodell=MODELL_NAME,
        )

    # 1. Verzeichnisse aussondern, bevor sie überhaupt Kandidat werden können
    if verzeichnisse_ausschliessen:
        kandidaten_chunks = [c for c in new_chunks if not ist_verzeichnis(c.text)]
    else:
        kandidaten_chunks = list(new_chunks)

    if not kandidaten_chunks:
        leer = {nr: {"status": "N", "begruendung": "", "fundstelle": ""}
                for nr in (k["nr"] for k in kriterien)}
        ergebnis = {"lh_id": lh_id, "bewertungen": leer,
                    "zusatzanforderungen": [], "hinweise": [],
                    "markierung": markierung,
                    "steckbrief": _steckbrief(),
                    "entscheider": ("nicht aktiv: keine prüfbaren Abschnitte"
                                    if mit_entscheider else "aus"),
                    "nicht_bewertet": 0}
        ergebnis["kennzahlen"] = kennzahlen(ergebnis, kriterien)
        return ergebnis, {}

    # Volltext für die Herkunftsprüfung. Bewusst über ALLE Abschnitte, auch die
    # aussortierten Verzeichnisse: Die Frage ist, ob eine Angabe irgendwo im
    # Kundendokument steht — nicht, ob sie an einer wertbaren Stelle steht.
    dok_text = " ".join(c.text for c in new_chunks).lower()

    # 2./3. Suche je Kriterium — dieselbe Funktion nutzt der Praxisabgleich
    if skaliere_fundstellen:
        n_fundstellen = fundstellen_zahl(len(kandidaten_chunks), n_fundstellen)
    fundstellen, kandidaten_chunks, query_vecs = fundstellen_je_kriterium(
        kandidaten_chunks, kriterien, standard, n_fundstellen=n_fundstellen,
        min_score=min_score, lexikalisches_gewicht=lexikalisches_gewicht,
        verzeichnisse_ausschliessen=False,   # oben bereits geschehen
        statistik=statistik,
    )

    # 4. Optional: Index über die Einzelaussagen des Standards, für Querverweise
    #    aus fremden Abschnitten. Einmal für alle 67 Kriterien.
    qv_index = None
    if mit_querverweisen and standard:
        from src.pruefung.standard_suche import Querverweisindex
        qv_index = Querverweisindex(standard)

    beispielquelle = None
    if referenzbeispiele:
        from src.pruefung.referenzbeispiele import Referenzbeispiele
        beispielquelle = Referenzbeispiele() or None
    ohne_dokument = {lh_id, Path(str(lh_id)).stem}

    bewertungen: dict[str, dict] = {}
    details:     dict[str, dict] = {}
    getroffene_chunks: set[int] = set()

    total = len(kriterien)
    verbindungsfehler_in_folge = 0
    modell_tot = ""          # der Grund, sobald der Lauf aufgegeben hat

    for i, (kriterium, qvec) in enumerate(zip(kriterien, query_vecs), start=1):
        nr    = kriterium["nr"]
        chunk = standard.get(nr)
        if progress_callback:
            progress_callback(i, total, f"{nr} {kriterium['titel']}")

        begriffe   = (chunk or kriterium).get("abgleichbegriffe", [])
        kandidaten = fundstellen[nr]

        if not kandidaten:
            # Keine Fundstelle → R1 greift, kein LLM-Aufruf nötig.
            bewertungen[nr] = {"status": "N", "begruendung": "", "fundstelle": ""}
            details[nr] = {"kandidaten": [], "raw": "",
                           "grund": KEIN_KANDIDAT}
            continue

        if modell_tot:
            # Nicht mehr anfragen — das Modell antwortet nicht. Der Grund bleibt
            # je Kriterium stehen, damit nicht_bewertete() jedes einzelne zählt.
            bewertungen[nr] = {"status": "N", "begruendung": "", "fundstelle": ""}
            details[nr] = {"kandidaten": kandidaten, "raw": "",
                           "grund": f"nicht angefragt — {modell_tot}"}
            continue

        getroffene_chunks.update(c["chunk"] for c in kandidaten)

        querverweise = ""
        if qv_index is not None:
            from src.pruefung.standard_suche import formatiere_querverweise
            querverweise = formatiere_querverweise(
                qv_index.suche(qvec, nr, begriffe=begriffe, n=n_querverweise,
                               min_score=min_querverweis_score))

        # Getrennt gehalten, weil die Herkunftsprüfung genau diesen Block
        # braucht — der ganze Prompt enthält auch die Fundstellen, und die
        # stammen aus dem Dokument.
        massstab = _format_standard(kriterium, chunk, querverweise,
                                    mit_fabrikatshinweis, erzeugnishinweis_weit,
                                    feld=feld)
        if beispielquelle is not None:
            massstab += beispielquelle.block(nr, ohne_dokument)
        try:
            prompt = template.format(
                nr=nr,
                titel=kriterium["titel"],
                kapitel=kriterium["kapitel"],
                begriffe=", ".join(begriffe) or "—",
                standard=massstab,
                # Die Beleglage wird dem Fundstellenblock vorangestellt statt
                # über einen eigenen Platzhalter geführt — so bleiben Vorlagen
                # ohne diesen Platzhalter gültig.
                fundstellen=((_beleglage(kandidaten) if mit_beleglage else "")
                             + _format_fundstellen(kandidaten)),
            )
        except (KeyError, IndexError, ValueError) as e:
            # Bearbeiteter Prompt mit kaputten Platzhaltern — sofort abbrechen,
            # statt 67-mal denselben Fehler zu produzieren.
            raise ValueError(
                f"Prompt-Vorlage fehlerhaft: {e}. Erlaubte Platzhalter: "
                "{nr}, {titel}, {kapitel}, {begriffe}, {standard}, {fundstellen}. "
                "Geschweifte Klammern im Beispiel-JSON müssen verdoppelt werden."
            ) from e

        antwort = (_chat(model, prompt, num_predict=num_predict,
                         mit_statuswahrscheinlichkeit=True)
                   if mit_wahrscheinlichkeiten else
                   _chat(model, prompt, num_predict=num_predict))

        if not antwort.ok:
            # Ein gescheiterter Aufruf darf den Lauf nicht verwerfen — aber er
            # darf auch nicht als „keine Vorgabe" durchgehen. Der Grund wandert
            # in details und wird von nicht_bewertete() eingesammelt.
            bewertungen[nr] = {"status": "N", "begruendung": "", "fundstelle": ""}
            details[nr] = {"kandidaten": kandidaten, "raw": "", "grund": antwort.grund,
                           "prompt": prompt}
            if ist_verbindungsfehler(antwort.grund):
                verbindungsfehler_in_folge += 1
                if verbindungsfehler_in_folge >= MAX_VERBINDUNGSFEHLER_IN_FOLGE:
                    modell_tot = antwort.grund
            else:
                verbindungsfehler_in_folge = 0
            continue
        verbindungsfehler_in_folge = 0

        geparst = _gelesene_bewertung(antwort.text)
        if geparst is None:
            # Kein JSON, kein zulässiger Status: ein Werkzeugausfall, kein Urteil.
            bewertungen[nr] = {"status": "N", "begruendung": "", "fundstelle": ""}
            details[nr] = {"kandidaten": kandidaten, "raw": antwort.text,
                           "grund": f"{ANTWORT_UNLESBAR}: {antwort.text[:120]!r}",
                           "prompt": prompt}
            continue

        # Bewusst in zwei Schritten, obwohl eine Zeile genügen würde: Zwischen
        # dem, was das Modell gesagt hat, und dem, was im Bericht steht, liegt
        # die Belegpflicht (R1) — sie stuft E/T/A ohne Begründung oder ohne
        # Seitenzahl auf N herunter. Diese Korrektur war bislang unsichtbar;
        # wer ein „keine Vorgabe" nicht verstand, konnte nicht erkennen, ob das
        # Modell nichts gefunden oder ob die Regel eingegriffen hat.
        bewertung = _erzwinge_belegpflicht(dict(geparst), kandidaten)
        details[nr] = {"kandidaten": kandidaten, "raw": antwort.text, "grund": "",
                       "prompt": prompt, "geparst": geparst,
                       # Herkunftsprüfung: harte Angaben der Begründung, die im
                       # Dokument fehlen und im Maßstab stehen. Ändert den
                       # Status nicht — siehe src/pruefung/herkunft.py.
                       "echo": herkunft.echo_angaben(
                           bewertung.get("begruendung", ""), dok_text, massstab)
                       if bewertung["status"] != "N" else []}

        # Gezielter Abweichungs-Durchgang: nur wenn der Punkt als geregelt gilt
        # und die Belegstelle einen sprachlichen Auslöser enthält.
        if mit_abweichungspass and bewertung["status"] in ("E", "T"):
            befund = _pruefe_abweichung(nr, kriterium["titel"], chunk, kandidaten,
                                        model, num_predict, details[nr])
            if befund is not None:
                bewertung = befund

        if mit_wahrscheinlichkeiten and getattr(antwort, "status_p", None):
            bewertung["wahrscheinlichkeit"] = antwort.status_p
        bewertungen[nr] = bewertung

    if mit_gegenteil and not modell_tot:
        from src.pruefung import gegenteil
        gegenteil.eintragen(bewertungen, details, kriterien, standard, model, _chat,
                            progress_callback=progress_callback)

    if mit_n_nachpruefung:
        from src.pruefung.nachpruefung import nachpruefen
        nachpruefen({"bewertungen": bewertungen}, details, kriterien, standard,
                    model, _chat, num_predict, feld=feld,
                    progress_callback=progress_callback)

    entscheider_stand = "aus"
    if mit_entscheider:
        from src.pruefung import entscheider as EN
        e_modell, grund = EN.laden(standard, suche=EN._suche(
            n_fundstellen, min_score, lexikalisches_gewicht, ENGLISCHE_BEGRIFFE))
        if e_modell is None:
            entscheider_stand = f"nicht aktiv: {grund}"
        else:
            n = EN.heben(bewertungen, details, kriterien, len(new_chunks), e_modell)
            entscheider_stand = f"{n} gehoben"
            if e_modell.get("uebertragen_von"):
                entscheider_stand += f", übertragen von {e_modell['uebertragen_von']}"
            # Ohne Modellwahrscheinlichkeiten ordnet der Rangierer die
            # Zusatzplätze der Markierung „gründlich".
            EN.rangieren(bewertungen, details, kriterien, standard, len(new_chunks), e_modell)
            # Grundrate A je Kriterium — das Anzeichen „Häufung" der Markierung.
            EN.anteil_eintragen(bewertungen, e_modell)

    ergebnis = {
        "lh_id": lh_id,
        "bewertungen": bewertungen,
        "zusatzanforderungen": [],
        "steckbrief": _steckbrief(),
    }

    # Hinweise stehen NEBEN den Bewertungen und gehen bewusst nicht in die
    # Kennzahlen ein — sie ändern keinen Status. Deshalb hier, nach der
    # Schleife: Ein Fehler im Durchgang darf die Prüfung nicht gefährden.
    if modell_tot:
        # Hinweis-Durchgang und Zusatzanforderungen brauchen das Modell.
        ergebnis["hinweise"] = []
        mit_hinweisen = mit_zusatzanforderungen = False

    if mit_hinweisen:
        ergebnis["hinweise"] = _hinweise(
            kriterien, standard, fundstellen, model, num_predict,
            progress_callback, feld=feld,
        )
        # Zweiter Weg, ohne Modellaufruf: die Begründungen, die der Agent oben
        # selbst geschrieben hat. Er nennt die Fabrikatsbindung dort häufig und
        # stuft trotzdem E ein — siehe src/hinweise.aus_begruendungen. Läuft
        # nach dem Modelldurchgang und überspringt dessen Kriterien, damit
        # dieselbe Stelle nicht zweimal im Bericht steht.
        from src.pruefung.hinweise import aus_begruendungen

        ergebnis["hinweise"] += [
            {"nr": h.nr, "art": h.art, "text": h.text,
             "fundstelle": h.fundstelle, "offene_stelle": h.offene_stelle}
            for h in aus_begruendungen(
                ergebnis, standard, fundstellen,
                schon_gemeldet={h["nr"] for h in ergebnis["hinweise"]},
            )
        ]

    if mit_zusatzanforderungen:
        ergebnis["zusatzanforderungen"] = _zusatzanforderungen(
            kandidaten_chunks, getroffene_chunks, model, progress_callback,
            feld=feld, anzahl=len(kriterien),
        )

    ergebnis["entscheider"] = entscheider_stand

    # Wie viele Kriterien stehen auf N, weil das WERKZEUG versagt hat — nicht,
    # weil der Kunde nichts vorgibt? Bisher stand das nur in `details`, also
    # weder im JSON noch im Excel-Bericht. Ein Lauf ohne Ollama sah damit aus
    # wie ein Lauf über ein leeres Lastenheft.
    ergebnis["nicht_bewertet"] = len(nicht_bewertete(details))

    # Markenvorgaben aus den Fundstellen — ein Anzeichen der Markierung „gründlich".
    from src.pruefung import markenvorgabe
    markenvorgabe.eintragen(bewertungen, details, kriterien)
    # Kostenfolgen aus den Fundstellen — Anzeichen der Markierung (Codebook R10).
    from src.pruefung import kostenfolge
    kostenfolge.eintragen(bewertungen, details, standard)
    # Werte und Werkstoffe außerhalb dessen, was der Standard belegt (Codebook R7).
    from src.pruefung import wertabgleich
    wertabgleich.eintragen(bewertungen, details, standard)

    # Nach Hinweisen und Zusatzanforderungen: Die Markierung braucht die Hinweise.
    from src.pruefung.markierung import markieren
    markieren(ergebnis, markierung)

    # Kennzahlen rechnet der Code, nicht das Modell.
    ergebnis["kennzahlen"] = kennzahlen(ergebnis, kriterien)

    return ergebnis, details


KEIN_KANDIDAT = "keine Stelle über der Relevanzschwelle"


def n_gruende(ergebnis: dict, details: dict) -> dict[str, int]:
    """Schlüsselt auf, WARUM ein Kriterium auf N steht.

    Drei völlig verschiedene Sachverhalte sehen im Bericht gleich aus:

    modell          Das Modell hat geurteilt: der Kunde regelt den Punkt nicht.
                    Nur das ist eine Aussage über das Lastenheft.
    ohne_kandidaten Die Suche fand keine Stelle über der Schwelle — es gab also
                    gar nichts zu bewerten. Meist ein Hinweis, dass die Schwelle
                    für dieses Dokument zu hoch steht (verrauschter OCR-Text).
    fehler          Der LLM-Aufruf schlug fehl. Werkzeugproblem, kein Befund.
    """
    out = {"modell": 0, "ohne_kandidaten": 0, "fehler": 0}
    for nr, b in ergebnis.get("bewertungen", {}).items():
        if b.get("status") != "N":
            continue
        grund = (details.get(nr) or {}).get("grund", "")
        if not grund:
            out["modell"] += 1
        elif grund == KEIN_KANDIDAT:
            out["ohne_kandidaten"] += 1
        else:
            out["fehler"] += 1
    return out


def _hinweise(kriterien: list[dict], standard: dict[str, dict],
              fundstellen: dict[str, list[dict]], model: str,
              num_predict: int, progress_callback=None,
              feld: "anwendungsfeld.Anwendungsfeld | None" = None) -> list[dict]:
    """Durchgang über die Kriterien, in denen der Standard offen formuliert.

    Ohne Standard gibt es keine offene Stelle und damit nichts zu fragen.
    """
    from src.pruefung.hinweise import offene_kriterien, pruefe_hinweise

    if not standard:
        return []
    offen = offene_kriterien(standard)
    titel = {k["nr"]: k["titel"] for k in kriterien}
    gefunden: list[dict] = []
    # Dieselbe Stelle des Lastenhefts belegt oft mehrere benachbarte Kriterien.
    # Im Bericht ist eine doppelte Meldung Rauschen, kein zweiter Befund.
    gesehen: set[str] = set()

    for i, (nr, stelle) in enumerate(offen.items(), start=1):
        kandidaten = fundstellen.get(nr) or []
        if not kandidaten:
            continue
        if progress_callback:
            progress_callback(i, len(offen), f"Hinweise {nr}")
        for h in pruefe_hinweise(nr, titel.get(nr, nr),
                                 _format_standard(
                                     {"titel": titel.get(nr, nr),
                                      "abgleichbegriffe": []}, standard.get(nr),
                                     feld=feld),
                                 stelle, kandidaten, model, _chat, num_predict,
                                 feld=feld):
            schluessel = " ".join(h.text.lower().split())
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            gefunden.append({"nr": h.nr, "art": h.art, "text": h.text,
                             "fundstelle": h.fundstelle,
                             "offene_stelle": h.offene_stelle})
    return gefunden


def _pruefe_abweichung(nr: str, titel: str, chunk: dict | None, kandidaten: list[dict],
                       model: str, num_predict: int, detail: dict) -> dict | None:
    """Führt den Abweichungs-Durchgang für ein Kriterium aus.

    Ein Aufruf über alle Belegstellen. Gibt die neue Bewertung zurück oder None,
    wenn es bei der bisherigen bleibt.
    """
    from src.pruefung.abweichung import pruefe_abweichung

    standard_text = _format_standard({"titel": titel, "abgleichbegriffe": []}, chunk)
    befund = pruefe_abweichung(nr, titel, standard_text, kandidaten,
                               model, _chat, num_predict)
    detail["abweichung_geprueft"] = True

    if befund.ist_abweichung:
        detail["abweichung_art"] = befund.art
        return {"status": "A", "begruendung": befund.begruendung,
                "fundstelle": befund.fundstelle}
    return None


def nicht_bewertete(details: dict) -> list[tuple[str, str]]:
    """Kriterien, die das Modell nicht bewerten konnte, als [(nr, grund)].

    Diese stehen im Ergebnis als N, sind aber KEINE Aussage des Kunden. Wer den
    Bericht liest, muss das unterscheiden können — sonst wird ein
    Werkzeugversagen als „Kunde gibt nichts vor" gelesen.

    Die Schwellenwert-Fälle („keine Stelle über der Relevanzschwelle") zählen
    nicht dazu: dort hat die Belegpflicht regulär gegriffen.
    """
    return [
        (nr, d["grund"]) for nr, d in sorted(details.items())
        if d.get("grund") and d["grund"] != KEIN_KANDIDAT
    ]


def _zusatzanforderungen(chunks: list, getroffene: set[int], model: str,
                          progress_callback=None, max_chunks: int = 25,
                          feld: "anwendungsfeld.Anwendungsfeld | None" = None,
                          anzahl: int | None = None) -> list[str]:
    """Sammelt Kundenanforderungen, die keinem Kriterium zugeordnet wurden."""
    uebrig = [(i, c) for i, c in enumerate(chunks) if i not in getroffene]
    if not uebrig:
        return []

    # Die längsten übrigen Abschnitte haben am ehesten Anforderungscharakter.
    uebrig.sort(key=lambda ic: len(ic[1].text), reverse=True)
    ausgewaehlt = sorted(uebrig[:max_chunks], key=lambda ic: ic[0])

    if progress_callback:
        progress_callback(1, 1, "Zusatzanforderungen")

    abschnitte = "\n\n---\n\n".join(f"[Seite {c.page}]\n{c.text}" for _, c in ausgewaehlt)

    vorlage = anwendungsfeld.uebertragen(ZUSATZ_PROMPT, feld, anzahl, format_sicher=True)
    antwort = _chat(model, vorlage.format(abschnitte=abschnitte))
    if not antwort.ok:
        return []

    blob = _first_json(antwort.text, opener="[")
    if not blob:
        return []
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(x).strip() for x in data if str(x).strip()]


# ── Kennzahlen (Formeln aus dem Codebook) ─────────────────────────────────────
def kennzahlen(ergebnis: dict, kriterien: list[dict] | None = None) -> dict:
    """Rechnet die Kennzahlen aus den Statuswerten — nicht das Modell tut das.

        geregelt          = E + T + A
        Abweichungsquote  = (A + 0,5 × T) / geregelt
        Abdeckungsquote   = geregelt / Zahl der Kriterien
        Konformitätsquote = E / geregelt

    Nicht geregelte Kriterien (N) fallen aus dem Nenner der Abweichungsquote
    heraus; die Abdeckungsquote weist die Lücken getrennt aus.

    Gezählt wird das Urteil des Modells, nicht die Markierung. Ein Kriterium, das
    src/pruefung/markierung.py nachträglich auf `A` gehoben hat, trägt seinen
    Modellstatus in `status_modell` und zählt unter diesem. Unter „gründlich“ sind
    das etliche Stellen je Lastenheft, von denen die meisten unbedenklich sind —
    als `A` gezählt, wäre die Abweichungsquote ein Maß für Verdachtsfälle. Sie
    stehen getrennt in `markiert`.
    """
    kriterien   = kriterien if kriterien is not None else load_kriterien()
    reihenfolge = [k["nr"] for k in kriterien]
    bewertungen = ergebnis.get("bewertungen", {})

    zaehler = {s: 0 for s in STATUS_WERTE}
    markiert = 0
    for nr in reihenfolge:
        status = modellstatus(bewertungen.get(nr))
        if status in zaehler:
            zaehler[status] += 1
        if ist_markiert(bewertungen.get(nr)):
            markiert += 1

    e, t, a, n = zaehler["E"], zaehler["T"], zaehler["A"], zaehler["N"]
    geregelt = e + t + a

    return {
        "entspricht":         e,
        "teilweise":          t,
        "abweichung":         a,
        "keine_vorgabe":      n,
        "geregelt":           geregelt,
        "abweichungsquote":   round((a + 0.5 * t) / geregelt, 6) if geregelt else None,
        "abdeckungsquote":    round(geregelt / len(reihenfolge), 6) if reihenfolge else 0.0,
        "konformitaetsquote": round(e / geregelt, 6) if geregelt else None,
        # Zur Durchsicht auf A gehoben, in den Zählern oben unter dem Modellstatus.
        "markiert":           markiert,
    }


def ist_markiert(bewertung: dict | None) -> bool:
    """Hat die Markierung dieses Kriterium auf `A` gehoben (das Modell nicht)?"""
    b = bewertung if isinstance(bewertung, dict) else {}
    return b.get("status") == "A" and b.get("status_modell") not in (None, "A")


def modellstatus(bewertung: dict | None) -> str | None:
    """Der Status, wie ihn das Modell (samt Entscheider) vergeben hat — vor der Markierung."""
    b = bewertung if isinstance(bewertung, dict) else {}
    return b.get("status_modell") if ist_markiert(b) else b.get("status")


def kennzahlen_je_einstufung(ergebnis: dict,
                             kriterien: list[dict] | None = None) -> dict[str, dict]:
    """Statusverteilung getrennt nach Pflicht / Regel / Optional.

    Ein fehlendes Pflichtkriterium ist ein Prüfhinweis an den Fachbereich, ein
    fehlendes Optionalkriterium normalerweise nicht.
    """
    kriterien   = kriterien if kriterien is not None else load_kriterien()
    bewertungen = ergebnis.get("bewertungen", {})

    out = {e: {s: 0 for s in STATUS_WERTE} for e in EINSTUFUNGEN}
    for k in kriterien:
        status = modellstatus(bewertungen.get(k["nr"]))
        if status in STATUS_WERTE and k["einstufung"] in out:
            out[k["einstufung"]][status] += 1
    return out


# ── Validierung (Agent_Instruktion.md, Abschnitt 4) ───────────────────────────
def validate(ergebnis: dict, kriterien: list[dict] | None = None) -> list[str]:
    """Prüft eine Agentenausgabe gegen die Struktur. Gibt die Liste der Verstöße zurück."""
    kriterien = kriterien if kriterien is not None else load_kriterien()
    erwartet  = [k["nr"] for k in kriterien]
    fehler: list[str] = []

    if not isinstance(ergebnis.get("lh_id"), str) or not ergebnis["lh_id"].strip():
        fehler.append("lh_id fehlt oder ist leer.")

    bewertungen = ergebnis.get("bewertungen")
    if not isinstance(bewertungen, dict):
        return fehler + ["bewertungen fehlt oder ist kein Objekt."]

    fehlend = [nr for nr in erwartet if nr not in bewertungen]
    if fehlend:
        fehler.append(f"Fehlende Kriterien ({len(fehlend)}): {', '.join(fehlend)}")

    unbekannt = [nr for nr in bewertungen if nr not in erwartet]
    if unbekannt:
        fehler.append(f"Unbekannte Nummern: {', '.join(unbekannt)}")

    for nr in erwartet:
        b = bewertungen.get(nr)
        if not isinstance(b, dict):
            continue
        status = b.get("status")
        if status not in STATUS_WERTE:
            fehler.append(f"{nr}: unzulässiger Status {status!r}")
            continue
        if status == "N":
            if b.get("begruendung") or b.get("fundstelle"):
                fehler.append(f"{nr}: Status N, aber begruendung/fundstelle nicht leer")
        else:
            if not str(b.get("begruendung", "")).strip():
                fehler.append(f"{nr}: Status {status} ohne Begründung")
            if not str(b.get("fundstelle", "")).strip():
                fehler.append(f"{nr}: Status {status} ohne Fundstelle — Belegpflicht verletzt, wäre N")

    if not isinstance(ergebnis.get("zusatzanforderungen", []), list):
        fehler.append("zusatzanforderungen ist keine Liste.")

    # Ein N aus einem Werkzeugausfall ist strukturell gültig und trotzdem keine
    # Aussage über das Lastenheft. Ohne diese Zeile winkte die Validierung einen
    # Lauf ohne Ollama als „in Ordnung" durch.
    offen = ergebnis.get("nicht_bewertet")
    if isinstance(offen, int) and offen > 0:
        fehler.append(f"{offen} Kriterien nicht bewertet (Werkzeugausfall, stehen als N) "
                      f"— Kennzahlen nicht belastbar")

    return fehler
