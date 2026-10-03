"""Das Entwurfssystem „Industry", auf Streamlit übertragen.

Die Vorlage ist ein HTML-Mockup mit eigenem Stylesheet. Sie lässt sich nicht
einsetzen wie sie ist — Streamlit erzeugt sein eigenes Markup, und der Entwurf
sagt selbst, dass er eine Referenz ist und keine Produktionsvorlage. Übertragen
wird deshalb, nicht kopiert: Die Token stehen hier einmal, die Bauteile werden
als kleine HTML-Schnipsel gerendert, und Streamlits eigene Bedienelemente
bekommen über Attributselektoren dasselbe Aussehen.

## Was das Gerüst trägt und was nicht

Streamlit vergibt für seine inneren Elemente erzeugte Klassennamen, die sich
mit jeder Version ändern können. Hier wird ausschließlich über
`data-testid`-Attribute und `[data-baseweb]` gearbeitet — beides gehört zur
öffentlichen Testschnittstelle und ist deutlich stabiler. Wo auch das nicht
reicht (die Eckmarken der Blaupausen-Rahmen), wird eigenes HTML gerendert
statt Streamlits Markup zu verbiegen.

## Die Statusfarben

Der Entwurf verzichtet bewusst auf Rot und Grün: Der Schweregrad wird über
Tonwert und Form gezeigt, nicht über Farbton. E ist ein neutrales Etikett mit
Haken, T ein helles Akzent-Etikett mit halb gefülltem Kreis, A ein
DUNKEL GEFÜLLTES Etikett mit Warndreieck, N ein Umriss mit leerem Kreis.

Das ist keine Geschmacksfrage. Rot-Grün ist für einen Teil der Nutzer nicht
unterscheidbar, und die vier Status sind der Kern der Ausgabe. Tonwert plus
Form funktioniert auch ausgedruckt und in Graustufen — und Prüfberichte werden
ausgedruckt.
"""

from __future__ import annotations

import html as _html

import streamlit as st

# ── Token ─────────────────────────────────────────────────────────────────────
# Wörtlich aus styles.css des Entwurfspakets. Sie stehen zusätzlich in
# .streamlit/config.toml, weil Streamlit einige Bedienelemente selbst einfärbt
# und dafür sein eigenes Thema liest. Ändert sich hier ein Wert, gehört er
# dort ebenfalls geändert — das ist die eine Doppelung, die sich nicht
# vermeiden lässt.
BG        = "#f2f2f3"
SURFACE   = "#e9e9ea"
TEXT      = "#1d1f20"
ACCENT    = "#5980a6"
ACCENT_100 = "#eef6ff"
ACCENT_700 = "#3a5876"
ACCENT_800 = "#2c455d"
NEUTRAL_100 = "#f5f5f8"
NEUTRAL_800 = "#33333a"
MUTED     = "rgba(29,31,32,0.72)"

STATUS_TEXT = {
    "E": "entspricht",
    "T": "teilweise",
    "A": "Abweichung",
    "N": "keine Vorgabe",
}

# Lucide-Stil, Strichstärke 2, currentColor — wie im Entwurf.
_ICON = {
    "E": '<path d="M20 6 9 17l-5-5"/>',
    "T": ('<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" '
          'stroke-width="2"/><path d="M12 3a9 9 0 0 1 0 18z" '
          'fill="currentColor" stroke="none"/>'),
    "A": ('<path d="M10.3 3.86 1.8 18a2 2 0 0 0 1.7 3h16.9a2 2 0 0 0 1.7-3'
          'L13.7 3.86a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>'),
    "N": '<circle cx="12" cy="12" r="9"/>',
}

_TAG_KLASSE = {"E": "tag-neutral", "T": "tag-accent", "A": "tag-a",
               "N": "tag-outline"}


def _svg(pfad: str, groesse: int = 14) -> str:
    return (f'<svg width="{groesse}" height="{groesse}" viewBox="0 0 24 24" '
            f'fill="none" stroke="currentColor" stroke-width="2" '
            f'aria-hidden="true">{pfad}</svg>')


def status_tag(status: str) -> str:
    """Das Statusetikett als HTML-Schnipsel — Symbol plus Buchstabe.

    Der Buchstabe steht immer daneben. Ein Symbol allein wäre eine
    Geheimsprache, und die vier Kürzel sind im Haus eingeführt.
    """
    s = status if status in _ICON else "N"
    return (f'<span class="tag {_TAG_KLASSE[s]}" '
            f'title="{s} — {STATUS_TEXT[s]}">{_svg(_ICON[s])}{s}</span>')


def _ecken() -> str:
    """Die vier Registermarken einer Blaupausen-Umrandung."""
    return "".join(f'<span class="corner {p}"></span>'
                   for p in ("tl", "tr", "bl", "br"))


def blueprint(inhalt: str, klassen: str = "") -> str:
    """Hairline-Rahmen mit Eckmarken um beliebiges HTML."""
    return (f'<div class="blueprint {klassen}">{_ecken()}'
            f'<div class="bp-inner">{inhalt}</div></div>')


def kennzahl(label: str, wert, hinweis: str = "") -> str:
    """Eine Kennzahl im Blaupausen-Rahmen.

    Ersetzt st.metric dort, wo mehrere nebeneinanderstehen: Streamlits
    Kennzahlkachel bringt eigene Abstände mit, die sich mit dem Raster des
    Entwurfs beißen.
    """
    # Der Erklärtext steht hinter einem sichtbaren „?“ — wie das Hilfesymbol der
    # Streamlit-Elemente. Ein Tooltip, von dem niemand weiß, findet niemand.
    hilfe = (f' <span class="kz-hilfe" title="{_html.escape(hinweis, quote=True)}">?</span>'
             if hinweis else "")
    return blueprint(
        f'<div class="kz">'
        f'<span class="kz-label">{_html.escape(str(label))}{hilfe}</span>'
        f'<span class="kz-wert">{_html.escape(str(wert))}</span></div>')


def kriteriumszeile(status: str, nr: str, titel: str, einstufung: str) -> str:
    """Die Kopfzeile eines Kriteriums — Etikett, Nummer, Titel, Einstufung."""
    return (f'<div class="krit">{status_tag(status)}'
            f'<span class="krit-nr">{_html.escape(nr)}</span>'
            f'<span class="krit-titel">{_html.escape(titel)}</span>'
            f'<span class="krit-einstufung">{_html.escape(einstufung)}</span>'
            f'</div>')


def kapitel(text: str) -> str:
    return f'<h6 class="kapitel">{_html.escape(text)}</h6>'


_CHEVRON = ('<svg class="krit-chev" width="16" height="16" viewBox="0 0 24 24" '
            'fill="none" stroke="currentColor" stroke-width="1.5" '
            'aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>')


def kriterium_block(status: str, nr: str, titel: str, einstufung: str,
                    begruendung: str = "", fundstelle: str = "",
                    stellen: list[dict] | None = None,
                    herkunft: list[str] | None = None,
                    status_modell: str | None = None,
                    statistisch: bool = False) -> str:
    """Ein Kriterium als aufklappbare Blaupausen-Zeile.

    Bewusst natives <details>/<summary> statt st.expander. Streamlits Expander
    löst bei jedem Auf- und Zuklappen einen Serverdurchlauf aus; bei 67 Zeilen
    ruckelt die Liste dadurch spürbar. <details> klappt im Browser auf, ohne
    dass die Anwendung etwas davon mitbekommt — und der Zustand überlebt einen
    Neuaufbau der Seite ohnehin nicht, weder so noch so.

    Der zweite Grund: Die Beschriftung eines st.expander rendert kein HTML.
    Das Statusetikett des Entwurfs — Symbol plus Buchstabe plus Tonwert —
    ließe sich dort gar nicht darstellen; es bliebe beim Emoji.
    """
    # Nachträglich markierte Abweichungen tragen das in der Zeile: Die Durchsicht
    # soll die vom Modell selbst vergebenen A von den gehobenen trennen können.
    gehoben = bool(status_modell) and status_modell != status
    # Vom gelernten Entscheider aus N gehoben (src/pruefung/entscheider.py) — ohne
    # Begründung des Modells, deshalb eigens gekennzeichnet.
    zusatz = " · markiert" if gehoben else " · statistisch" if statistisch else ""
    zeile = kriteriumszeile(status, nr, titel, f"{einstufung}{zusatz}")
    stellen = stellen or []

    if not (begruendung or fundstelle or stellen):
        # Ohne Vorgabe gibt es nichts aufzuklappen: eine ruhige Zeile.
        return f'<div class="blueprint krit-still">{_ecken()}{zeile}</div>'

    # Reihenfolge mit Absicht: erst was im Lastenheft steht, dann was die
    # Software daraus macht.
    #
    # Die Suche legt die richtige Stelle verlässlicher vor, als die Einstufung
    # stimmt. Der verlässliche Teil gehört nach oben, das Urteil darunter — und als
    # Vorschlag beschriftet, nicht als Befund.
    #
    # Drei Stellen statt einer: Die zitierte Seite ist so deutlich öfter dabei. Mehr
    # als drei macht die Liste unlesbar, ohne dass der Gewinn mithält.
    teile = []
    if stellen:
        teile.append('<h6 class="krit-h">Was im Lastenheft steht</h6>')
        for s in stellen[:3]:
            seite = s.get("page")
            kopf = (f'<span class="krit-seite">Seite {seite}</span>'
                    if seite is not None else "")
            teile.append(f'<div class="krit-stelle">{kopf}'
                         f'<pre class="krit-beleg">'
                         f'{_html.escape((s.get("text") or "").strip())}</pre></div>')

    if begruendung or fundstelle:
        teile.append('<h6 class="krit-h">Vorschlag der Software</h6>')
        if begruendung:
            teile.append(f'<p class="krit-grund"><strong>{_html.escape(status)} — '
                         f'{STATUS_TEXT.get(status, "")}</strong> · '
                         f'{_html.escape(begruendung)}</p>')
        if fundstelle:
            teile.append(f'<span class="text-muted krit-fund">stützt sich auf '
                         f'{_html.escape(fundstelle)}</span>')
        if statistisch:
            teile.append('<p class="text-muted krit-fund">Statistisch gehoben — das Modell '
                         'hatte keine Vorgabe gesehen, die Suche spricht dagegen.</p>')
        if gehoben:
            teile.append(f'<p class="text-muted krit-fund">Als Abweichung markiert: '
                         f'{_html.escape(" · ".join(herkunft or []))} — das Modell '
                         f'hatte {_html.escape(status_modell)} vergeben.</p>')

    return (f'<details class="blueprint krit-block">{_ecken()}'
            f'<summary class="krit-summary">{zeile}{_CHEVRON}</summary>'
            f'<div class="krit-detail">{"".join(teile)}</div>'
            f'</details>')


# ── Das Stylesheet ────────────────────────────────────────────────────────────
# Ein Block, einmal je Sitzung eingespielt. Aufgeteilt in: Token, Grundlagen,
# eigene Bauteile, und zuletzt die Übersetzung auf Streamlits Bedienelemente.
_CSS = """
/* 600 ist zusätzlich geladen: Die kleinen Etiketten stehen in Halbfett, und
   ohne den echten Schnitt rechnet der Browser ihn aus dem Normalschnitt hoch —
   das Ergebnis ist bei 12 px matschig. */
@import url('https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700&family=Barlow+Condensed:wght@400;600;700&display=swap');

:root {
  --color-bg: #f2f2f3;
  --color-surface: #e9e9ea;
  --color-text: #1d1f20;
  --color-accent: #5980a6;
  --color-divider: rgba(29,31,32,0.16);

  --color-neutral-100: #f5f5f8;
  --color-neutral-800: #33333a;
  --color-accent-100: #eef6ff;
  --color-accent-600: #4a6d91;
  --color-accent-700: #3a5876;
  --color-accent-800: #2c455d;

  /* Gedämpfter Text. Der Entwurf setzt 55 % Deckung — das ergibt auf dem
     hellen Grund ein Kontrastverhältnis von 4,0:1 und liegt damit unter der
     Grenze von 4,5:1, die für Fließtext gilt. 0,72 bringt es auf 7,4:1 und
     bleibt trotzdem sichtbar zurückgenommen. */
  --color-muted: rgba(29,31,32,0.72);

  --font-heading: "Barlow Condensed", system-ui, sans-serif;
  --font-body: "Barlow", system-ui, sans-serif;

  /* Schriftgrade. Der Entwurf ist als Bild gezeichnet und geht bis 10 px
     herunter; am Bildschirm gelesen ist das zu klein, besonders in
     Großbuchstaben mit weiter Laufweite. Die Stufen stehen deshalb als Token
     hier und nicht als Pixelwerte in zwanzig Regeln. */
  --fs-klein: 13px;      /* Etiketten, Seitenangaben, Marginalien */
  --fs-label: 12px;      /* Versalien-Kleinlabels, mit enger Laufweite */
  --fs-text:  15px;      /* Fließtext, Kriterientitel, Bedienelemente */
  --fs-beleg: 14px;      /* Belegstellen in Festbreitenschrift */

  --space-1: 3.4px;  --space-2: 6.8px;  --space-3: 10.2px;
  --space-4: 13.6px; --space-6: 20.4px; --space-8: 27.2px;
}

/* ── Grundlagen ─────────────────────────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"], .stApp {
  background: var(--color-bg);
  color: var(--color-text);
  font-family: var(--font-body);
  font-size: var(--fs-text);
  line-height: 1.55;
}
/* Streamlit setzt seine Absatzgröße auf einer inneren Ebene und überschreibt
   damit die Vererbung von body. Deshalb hier ausdrücklich — sonst bleibt der
   Fließtext auf Streamlits 14 px, egal was oben steht. */
[data-testid="stAppViewContainer"] * { font-family: var(--font-body); }
[data-testid="stAppViewContainer"] p,
[data-testid="stAppViewContainer"] li,
[data-testid="stMarkdownContainer"] p {
  font-size: var(--fs-text); line-height: 1.55;
}

h1, h2, h3, h4, h5, h6 {
  font-family: var(--font-heading) !important;
  font-weight: 600 !important; line-height: 1.15; letter-spacing: -0.01em;
}
h1 { font-size: 36px !important; }
h2 { font-size: 28px !important; }
h3 { font-size: 22px !important; }
h4 { font-size: 19px !important; }
h5 { font-size: 16px !important; }
/* Versalien mit weiter Laufweite lesen sich schlechter als gemischte Schrift.
   Der Entwurf will diesen Ton, also bleibt er — aber einen Grad größer, mit
   halbierter Laufweite und in Halbfett, damit die dünnen Striche von Barlow
   Condensed bei dieser Größe noch tragen. */
h6 { font-size: var(--fs-label) !important; letter-spacing: 0.05em !important;
     font-weight: 700 !important; text-transform: uppercase; }

/* Streamlit-Bedienelemente ausblenden. „Deploy" und das Entwicklermenü haben
   in einem Werkzeug für den Betrieb nichts zu suchen. */
[data-testid="stToolbar"], [data-testid="stDecoration"],
#MainMenu, footer { display: none !important; }
[data-testid="stHeader"] { height: 0; background: transparent; }

.block-container { padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1120px; }

/* ── Blaupausen-Rahmen ──────────────────────────────────────────────────── */
/* Quadratisch, transparent, Haarlinie — und vier Registermarken, die über den
   Rand hinausragen. Deshalb padding am Container: Ohne Luft schneidet
   Streamlits Spaltenraster die Marken ab. */
.blueprint {
  position: relative; border: 1px solid var(--color-divider);
  border-radius: 0; background: transparent; margin: 6px 0;
}
.blueprint > .corner {
  position: absolute; width: 11px; height: 11px;
  color: rgba(29,31,32,0.55);
}
.blueprint > .corner::before, .blueprint > .corner::after {
  content: ""; position: absolute; background: currentColor;
}
.blueprint > .corner::before { left: 5px; top: 0; width: 1px; height: 100%; }
.blueprint > .corner::after  { top: 5px; left: 0; width: 100%; height: 1px; }
.blueprint > .corner.tl { top: -6px; left: -6px; }
.blueprint > .corner.tr { top: -6px; right: -6px; }
.blueprint > .corner.bl { bottom: -6px; left: -6px; }
.blueprint > .corner.br { bottom: -6px; right: -6px; }
.bp-inner { padding: var(--space-3); }

/* ── Etiketten ──────────────────────────────────────────────────────────── */
.tag {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: var(--fs-klein); font-weight: 600;
  letter-spacing: 0.02em; padding: 4px 10px; border-radius: 0;
  font-family: var(--font-body); white-space: nowrap;
}
.tag svg { display: block; }
.tag-neutral { background: var(--color-neutral-100); color: var(--color-neutral-800); }
.tag-accent  { background: var(--color-accent-100);  color: var(--color-accent-800); }
/* Der Akzentton #5980a6 kommt als Text auf hellem Grund nur auf 3,4:1 und ist
   damit für ein Etikett zu schwach. Der Umriss behält den hellen Akzent, die
   Schrift nimmt die dunklere Stufe. */
.tag-outline { border: 1px solid var(--color-accent); color: var(--color-accent-700); }
/* A trägt den Schweregrad über Tonwert, nicht über Farbton: das einzige
   voll gefüllte Etikett. */
.tag-a { background: var(--color-accent-800); color: var(--color-bg); }

/* ── Kennzahlen ─────────────────────────────────────────────────────────── */
.kz { display: flex; flex-direction: column; gap: 2px; }
.kz-label {
  font-size: var(--fs-label); font-weight: 600;
  letter-spacing: 0.05em; text-transform: uppercase;
  color: var(--color-accent-700);
}
.kz-wert {
  font-family: var(--font-heading); font-weight: 600; font-size: 30px;
  line-height: 1.1;
}
.kz-hilfe {
  display: inline-flex; align-items: center; justify-content: center;
  width: 17px; height: 17px; margin-left: 4px; border-radius: 50%;
  border: 1px solid var(--color-accent-700); font-size: 12px; font-weight: 700;
  text-transform: none; letter-spacing: 0; cursor: help; vertical-align: 1px;
}

/* ── Kriteriumszeilen ───────────────────────────────────────────────────── */
.kapitel { color: var(--color-accent-700); margin: var(--space-6) 0 var(--space-2); }
.krit {
  display: flex; align-items: center; gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
}
.krit-nr { font-family: var(--font-heading); font-weight: 700;
           font-size: var(--fs-text); min-width: 42px; }
.krit-titel { flex: 1; font-size: var(--fs-text); line-height: 1.4; }
.krit-einstufung { font-size: var(--fs-klein); color: var(--color-muted);
                   white-space: nowrap; }

.text-muted { color: var(--color-muted); }

/* Aufklappbare Kriteriumszeile — natives <details>, kein Serverdurchlauf. */
.krit-block, .krit-still { margin-bottom: var(--space-2); }
.krit-summary {
  display: flex; align-items: center; cursor: pointer; list-style: none;
  padding-right: var(--space-3);
}
.krit-summary::-webkit-details-marker { display: none; }
.krit-summary:hover { background: rgba(29,31,32,0.04); }
.krit-summary .krit { flex: 1; min-width: 0; }
/* Die Titel wurden mit Auslassungspunkten abgeschnitten. Das ist der Grund,
   warum die Zeile nicht mehr lesbar war: Bei 67 Kriterien passt gut die
   Hälfte der Titel nicht in eine Zeile, und abgeschnitten sind mehrere
   ununterscheidbar („Werkstoffe der formgebenden …"). Sie brechen jetzt auf
   höchstens zwei Zeilen um, statt zu verschwinden. */
.krit-titel {
  overflow: hidden; display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.krit-chev { flex: none; transition: transform 120ms ease;
             color: var(--color-muted); }
details[open] > .krit-summary .krit-chev { transform: rotate(90deg); }
/* Die stille Zeile war auf 72 % heruntergeblendet und lag damit unter dem
   Kontrastminimum. Zurückgenommen wird sie jetzt über die Textfarbe, nicht
   über die Deckung des ganzen Blocks. */
.krit-still .krit .krit-titel,
.krit-still .krit .krit-nr { color: var(--color-muted); }
.krit-detail {
  padding: 0 var(--space-3) var(--space-3);
  border-top: 1px solid var(--color-divider);
}
.krit-grund { margin: var(--space-2) 0 4px; font-size: var(--fs-text);
              line-height: 1.55; max-width: 82ch; }
.krit-fund { font-size: var(--fs-klein); }
.krit-h { margin: var(--space-4) 0 var(--space-2); color: var(--color-accent-700); }
.krit-h:first-child { margin-top: var(--space-3); }
.krit-stelle + .krit-stelle { margin-top: var(--space-3); }
.krit-seite { font-size: var(--fs-klein); color: var(--color-muted);
              font-family: var(--font-heading); font-weight: 600;
              letter-spacing: 0.03em; }
.krit-stelle .krit-beleg { margin-top: 4px; max-height: 210px; }

/* Der Güteanzeiger des Dokuments. */
.guete { display: flex; align-items: baseline; gap: var(--space-3);
         padding: var(--space-3) var(--space-4); font-size: var(--fs-text);
         line-height: 1.55;
         border-left: 3px solid var(--color-accent); background: var(--color-surface); }
.guete.schwach { border-left-color: var(--color-accent-800); }
.guete .wert { font-family: var(--font-heading); font-weight: 600;
               font-size: 22px; flex: none; }
/* Der Auszug aus dem Lastenheft. Festbreitenschrift, weil die Auszüge Tabellen
   und eingerückte Listen enthalten, die sonst zerfallen — aber einen Grad
   größer und luftiger gesetzt als der Entwurf vorsah. Dies ist der Text, den
   der Prüfer tatsächlich liest; er darf nicht der kleinste auf der Seite sein. */
.krit-beleg {
  margin: var(--space-2) 0 0; padding: var(--space-3) var(--space-4);
  max-height: 260px; overflow: auto;
  background: var(--color-surface); border: 1px solid var(--color-divider);
  font-family: ui-monospace, "Cascadia Mono", Consolas, monospace;
  font-size: var(--fs-beleg); line-height: 1.6;
  white-space: pre-wrap; word-break: break-word;
}

/* ── Notnagel gegen Streamlits Dunkelthema ──────────────────────────────── */
/* Streamlit liest `.streamlit/config.toml` relativ zum ARBEITSVERZEICHNIS des
   Prozesses, nicht relativ zum Skript. Wird die Anwendung aus einem anderen
   Ordner gestartet — `streamlit run Fallstudie/app.py` von einer Ebene höher —
   findet Streamlit die Datei nicht, fällt auf die Einstellung des
   Betriebssystems zurück und zeichnet sein Dunkelthema: Schrift in
   rgb(250,250,250).

   Der helle Grund kommt aber aus diesem Stylesheet und bleibt hell. Ergebnis
   ist weiße Schrift auf hellgrauem Grund — gemessen 1,07:1, praktisch
   unsichtbar. Betroffen war alles, was Streamlit selbst beschriftet:
   Kontrollkästchen, Auswahlfelder, Bildunterschriften, die Dateiauswahl.

   Der Entwurf hat keine dunkle Fassung (siehe .streamlit/config.toml), es gibt
   also nichts abzuwägen: Die Textfarbe wird hier festgenagelt. Gezielt wird auf
   Streamlits Bedienelemente, nicht pauschal — die eigenen Bauteile bringen
   ihre Farben mit, und ein `*`-Selektor würde das dunkel gefüllte
   A-Etikett und den Primärknopf gleich mit unlesbar machen. */
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] *,
[data-testid="stCheckbox"], [data-testid="stCheckbox"] *,
[data-testid="stRadio"] label, [data-testid="stSelectbox"] div,
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stSlider"] div, [data-testid="stExpander"] summary,
[data-testid="stFileUploaderDropzoneInstructions"] span,
[data-testid="stFileUploader"] button,
[data-testid="stAlert"], [data-testid="stAlert"] * {
  color: var(--color-text);
}
/* Zurückgenommener Text — dieselbe Lage, nur eine Stufe leiser. */
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] *,
[data-testid="stFileUploaderDropzoneInstructions"] small,
[data-testid="stFileUploader"] small {
  color: var(--color-muted) !important;
}
/* Fließtext aus st.markdown/st.write. Nur die UNMITTELBAREN Kinder: Die
   eigenen Bauteile werden ebenfalls über st.markdown eingespielt, liegen dort
   aber immer in einem <div> oder <details> und bleiben so unberührt. */
[data-testid="stMarkdownContainer"] > p,
[data-testid="stMarkdownContainer"] > ul, [data-testid="stMarkdownContainer"] > ol,
[data-testid="stMarkdownContainer"] > li,
[data-testid="stMarkdownContainer"] > h1, [data-testid="stMarkdownContainer"] > h2,
[data-testid="stMarkdownContainer"] > h3, [data-testid="stMarkdownContainer"] > h4,
[data-testid="stMarkdownContainer"] > h5, [data-testid="stMarkdownContainer"] > h6,
[data-testid="stMarkdownContainer"] > p * {
  color: var(--color-text);
}
/* Eingabefelder und Auswahllisten brauchen auch ihren Grund zurück, sonst
   steht dunkle Schrift auf Streamlits dunkler Fläche. */
[data-baseweb="input"], [data-baseweb="select"] > div,
[data-baseweb="textarea"], [data-baseweb="popover"] li {
  background: var(--color-bg) !important; color: var(--color-text) !important;
}
[data-baseweb="popover"] li:hover { background: var(--color-surface) !important; }

/* ── Streamlits eigene Bedienelemente ───────────────────────────────────── */
/* Alles eckig — der Entwurf setzt Radius 0 durchgehend. */
.stButton > button, .stDownloadButton > button,
[data-testid="stFileUploader"] section,
[data-baseweb="input"], [data-baseweb="select"] > div,
[data-testid="stExpander"] details, [data-testid="stNotification"] {
  border-radius: 0 !important;
}

.stButton > button, .stDownloadButton > button {
  font-family: var(--font-heading) !important; font-weight: 600 !important;
  font-size: 16px !important; letter-spacing: 0.01em;
  border: 1px solid var(--color-divider) !important;
  background: transparent; color: var(--color-text);
  transition: background 120ms ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  background: rgba(29,31,32,0.07); color: var(--color-text);
  border-color: var(--color-divider) !important;
}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
  background: var(--color-accent) !important; color: var(--color-bg) !important;
  border-color: var(--color-accent) !important;
}
.stButton > button[kind="primary"]:hover,
.stDownloadButton > button[kind="primary"]:hover {
  background: var(--color-accent-600) !important;
}
/* Streamlit legt die Beschriftung als <p> in den Knopf. Die Regel für
   Fließtext oben trifft dieses <p> ebenfalls und überschreibt Größe und
   Schnitt des Knopfes — die Beschriftung stand dadurch in 15 px mager statt
   in 16 px halbfett. */
.stButton > button p, .stDownloadButton > button p {
  font-family: inherit !important; font-size: inherit !important;
  font-weight: inherit !important; line-height: inherit;
  /* Auch die Farbe muss erben. Streamlit verpackt die Beschriftung in einen
     stMarkdownContainer, und der Notnagel gegen das Dunkelthema färbt dessen
     Absätze dunkel — auf dem blauen Grund des Primärknopfs waren das 3,99:1.
     Geerbt wird sie hell, wie der Knopf sie setzt. */
  color: inherit !important;
}
/* Ausgegraut, aber noch lesbar: Bei 0,45 fiel die Beschriftung unter 4:1 und
   man konnte nicht mehr erkennen, worauf man wartet. */
.stButton > button:disabled, .stDownloadButton > button:disabled {
  opacity: 0.6;
}

/* Dateiauswahl als gestrichelte Ablagefläche, wie im Entwurf. */
[data-testid="stFileUploader"] section {
  border: 1px dashed var(--color-divider) !important;
  background: transparent !important;
}

/* Reiter: Großbuchstaben-Navigation statt Streamlits Standardleiste. */
.stTabs [data-baseweb="tab-list"] {
  gap: var(--space-4); border-bottom: 1px solid var(--color-divider);
}
.stTabs [data-baseweb="tab"] {
  font-family: var(--font-heading); font-weight: 600; font-size: 17px;
  padding: 9px 2px; color: var(--color-text);
}
.stTabs [aria-selected="true"] { color: var(--color-accent) !important; }
.stTabs [data-baseweb="tab-highlight"] { background: var(--color-accent); }

/* Streamlits umrandete Container (st.container(border=True)) als Blaupause.
   Randlos und umrandet unterscheiden sich nur in einem ERZEUGTEN
   Klassennamen (st-emotion-cache-…), der beim nächsten Streamlit-Update
   anders heißen kann. Deshalb wird nicht darauf gezielt: Die Karte trägt eine
   eigene, leere Marke `.bp-card`, und :has() findet den Rahmen darüber.
   Radius und Randfarbe dürfen alle bekommen — bei Randbreite 0 ist beides
   folgenlos.

   Die Registermarken sitzen INNEN, nicht außen wie bei den selbst
   gerenderten Rahmen: Sie sind Hintergrundverläufe, und ein Hintergrund endet
   an der Rahmenkante. Marken außerhalb bräuchten Kindelemente im Container,
   an die ohne erzeugte Klassennamen nicht heranzukommen ist. Fünf Pixel
   Versatz gegen einen Rahmen, der hält. */
[data-testid="stVerticalBlockBorderWrapper"] {
  border-radius: 0 !important;
  border-color: var(--color-divider) !important;
}
.bp-card { display: none; }
/* :has() trifft jeden Vorfahren, nicht nur den nächsten — und Streamlit
   verschachtelt diese Container. Der zweite Teil schließt alle aus, bei denen
   die Marke noch einmal in einem inneren Container liegt: Übrig bleibt genau
   der Rahmen der Karte. */
[data-testid="stVerticalBlockBorderWrapper"]:has(.bp-card):not(
  :has([data-testid="stVerticalBlockBorderWrapper"] .bp-card)) {
  background:
    linear-gradient(var(--bp-mark), var(--bp-mark)) 5px 0    / 1px 11px no-repeat,
    linear-gradient(var(--bp-mark), var(--bp-mark)) 0    5px  / 11px 1px no-repeat,
    linear-gradient(var(--bp-mark), var(--bp-mark)) calc(100% - 5px) 0 / 1px 11px no-repeat,
    linear-gradient(var(--bp-mark), var(--bp-mark)) 100% 5px / 11px 1px no-repeat,
    linear-gradient(var(--bp-mark), var(--bp-mark)) 5px 100% / 1px 11px no-repeat,
    linear-gradient(var(--bp-mark), var(--bp-mark)) 0 calc(100% - 5px) / 11px 1px no-repeat,
    linear-gradient(var(--bp-mark), var(--bp-mark)) calc(100% - 5px) 100% / 1px 11px no-repeat,
    linear-gradient(var(--bp-mark), var(--bp-mark)) 100% calc(100% - 5px) / 11px 1px no-repeat;
}
:root { --bp-mark: rgba(29,31,32,0.55); }

[data-testid="stExpander"] details {
  border: 1px solid var(--color-divider) !important; background: transparent;
}
[data-testid="stExpander"] summary { font-size: var(--fs-text); }

/* Streamlits Kennzahlkachel — für die Stellen, an denen st.metric bleibt. */
[data-testid="stMetric"] {
  background: transparent; border: 1px solid var(--color-divider);
  border-radius: 0; padding: var(--space-3);
}
[data-testid="stMetricLabel"] p {
  font-size: var(--fs-label) !important; font-weight: 600 !important;
  letter-spacing: 0.05em; text-transform: uppercase;
  color: var(--color-accent-700) !important;
}
[data-testid="stMetricValue"] {
  font-family: var(--font-heading) !important; font-weight: 600 !important;
  font-size: 30px !important;
}

hr, [data-testid="stDivider"] hr {
  border-color: var(--color-divider); margin: var(--space-6) 0;
}

[data-testid="stSidebar"] { background: var(--color-surface); }
[data-testid="stSidebar"] .stMarkdown p {
  margin-bottom: var(--space-2); font-size: 14px !important; line-height: 1.5;
}

/* Die Kopfzeile der Anwendung. */
.kopf { border-bottom: 1px solid var(--color-divider);
        padding-bottom: var(--space-3); margin-bottom: var(--space-2); }
.kopf .kicker {
  font-size: var(--fs-label); font-weight: 600;
  letter-spacing: 0.05em; text-transform: uppercase;
  color: var(--color-accent-700);
}
.kopf h1 { margin: var(--space-2) 0 0 0; }
.kopf p { font-size: 16px; color: var(--color-muted); margin: var(--space-3) 0 0 0;
          max-width: 74ch; line-height: 1.55; }
"""


def einspielen() -> None:
    """Das Stylesheet einspielen. Einmal je Seitenaufbau, ganz oben."""
    st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)


def kopf(titel: str, text: str, kicker: str = "") -> None:
    k = f'<span class="kicker">{_html.escape(kicker)}</span>' if kicker else ""
    st.markdown(f'<div class="kopf">{k}<h1>{_html.escape(titel)}</h1>'
                f'<p>{text}</p></div>', unsafe_allow_html=True)


def karte() -> None:
    """Markiert den umgebenden st.container(border=True) als Blaupausen-Karte.

    Als erstes im Container aufrufen. Der Schnipsel ist unsichtbar; er dient
    nur als Anker für den CSS-Selektor, damit die Registermarken nicht an
    Streamlits erzeugten Klassennamen hängen.
    """
    st.markdown('<span class="bp-card"></span>', unsafe_allow_html=True)


def kennzahlenreihe(werte: list[tuple[str, object, str]]) -> None:
    """Mehrere Kennzahlen nebeneinander, im Raster des Entwurfs."""
    spalten = st.columns(len(werte))
    for spalte, eintrag in zip(spalten, werte):
        label, wert, hinweis = (eintrag + ("",))[:3] if len(eintrag) < 3 else eintrag
        with spalte:
            st.markdown(kennzahl(label, wert, hinweis), unsafe_allow_html=True)
