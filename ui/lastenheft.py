"""Lastenheft-Vergleichs-UI."""

import streamlit as st
import html as _html
import re
import tempfile
import json
import time
from pathlib import Path

from src.dokumente.pdf_loader import (
    SUPPORTED_SUFFIXES, TextExtraktionsFehler, load_document, ocr_status,
)
from src.pruefung import auftrag as A
from src.pruefung.kriterien import (
    fundstellen_je_kriterium, kennzahlen_je_einstufung,
    load_kriterien, load_standard, n_gruende, nicht_bewertete, validate,
)
from src.muster.standard_import import (
    StandardImportFehler, musterlastenheft_lesen, vergleiche_mit_bestand,
)
from src.muster import bibliothek
from src.bericht import demo
from src.praxis.abgleich import LABEL, korpus_ids, praxisabgleich, zusammenfassung
from src.praxis.archiv import Praxisarchiv, archiv_info, baue_archiv
from src.praxis import dokumentvergleich as DV
from src.bericht.excel_report import generate_excel
from ui.design import (
    STATUS_TEXT as DESIGN_STATUS_TEXT, kapitel as _kapitel_html,
    karte, kennzahlenreihe, kriterium_block, status_tag,
)
from ui.spur import kopf as spur_kopf, render as render_spur

BASE_DIR      = Path(__file__).parent.parent
MUSTER_PATH   = BASE_DIR / "data" / "muster"
OUTPUT_PATH   = BASE_DIR / "output"
# Der Ablageordner des Praxisarchivs gehört zum aktiven Musterlastenheft:
# bibliothek.historie_ordner().

for _folder in (MUSTER_PATH, OUTPUT_PATH):
    _folder.mkdir(parents=True, exist_ok=True)

UPLOAD_TYPES = [s.lstrip(".") for s in SUPPORTED_SUFFIXES]


# ── Musterlastenheft ───────────────────────────────────────────────────────
def _aktivieren_gewaehlt() -> None:
    """Nur bei echter Auswahl: Streamlit ruft das erst nach einer Änderung auf."""
    gewaehlt = st.session_state.get("muster_aktiv")
    if gewaehlt:
        bibliothek.aktivieren(gewaehlt)


def _render_bibliothek() -> None:
    eintraege = bibliothek.eintraege()
    aktiv = next((e for e in eintraege if e.aktiv), None)
    if not aktiv:
        st.warning("Kein Musterlastenheft hinterlegt — die Prüfung erkennt dann nur, "
                   "OB ein Punkt geregelt ist.")
        return

    je = {e.schluessel: e for e in eintraege}
    st.selectbox(
        "Aktives Musterlastenheft", list(je), index=list(je).index(aktiv.schluessel),
        format_func=lambda s: f"{je[s].name} · {je[s].kriterien} Kriterien",
        key="muster_aktiv", on_change=_aktivieren_gewaehlt,
        help="Gegen dieses Musterlastenheft wird geprüft. Praxisarchiv und "
             "Ablageordner gehören zum jeweiligen Musterlastenheft und wechseln mit.")
    st.caption(f"{aktiv.gegenstand} · Stand {aktiv.stand}")

    andere = [e for e in eintraege if not e.aktiv]
    if not andere:
        return
    with st.expander(f"Hinterlegte verwalten ({len(eintraege)})", expanded=False):
        for e in andere:
            links, rechts = st.columns([4, 1])
            links.markdown(f"{e.name} · {e.kriterien} Kriterien · {e.stand}")
            # Zwei Schritte: Entfernen löscht auch das Praxisarchiv des Eintrags.
            if st.session_state.get("muster_weg") == e.schluessel:
                if rechts.button("Endgültig", key=f"muster_weg_ja_{e.schluessel}",
                                 type="primary", help="Löscht Musterlastenheft, "
                                 "Praxisarchiv und Ablageordner dieses Eintrags."):
                    bibliothek.entfernen(e.schluessel)
                    st.session_state.pop("muster_weg", None)
                    st.rerun()
            elif rechts.button("Entfernen", key=f"muster_weg_{e.schluessel}"):
                st.session_state["muster_weg"] = e.schluessel
                st.rerun()


def _render_musterlastenheft() -> None:
    """Auswahl des aktiven Musterlastenhefts, Hochladen mit Vorschau.

    Hinterlegt wird erst auf Bestätigung. Vorher sieht man, was sich gegenüber
    einer gleichnamigen Fassung ändert — sonst wüsste niemand, was eine
    Überarbeitung bewirkt hat.
    """
    st.markdown("**Musterlastenheft**",
                help="Der Maßstab, gegen den geprüft wird. In Word bearbeiten und "
                     "hier hochladen. Mehrere lassen sich hinterlegen, eines ist aktiv.")
    _render_bibliothek()

    hochgeladen = st.file_uploader(
        "Musterlastenheft hochladen (.docx)", type=["docx"], key="muster_upload",
        help="Erwartet: nummerierte Überschriften („3.3 Formnull …“), je Abschnitt "
             "eine Kopfzeile mit Einstufung und Belegzahl, darunter „Standardanforderungen“, "
             "„Ausprägungen im Korpus“, „Projektspezifisch festzulegen“, „Abgleichbegriffe:“.")
    # Ein im Musteraufbau erzeugter Entwurf läuft durch dieselbe Vorschau wie
    # ein hochgeladenes Dokument — keine zweite, abgekürzte Übernahme.
    entwurf = st.session_state.get("muster_entwurf")
    if hochgeladen:
        ziel = MUSTER_PATH / hochgeladen.name
        ziel.write_bytes(hochgeladen.getvalue())
    elif entwurf and Path(entwurf).exists():
        ziel = MUSTER_PATH / Path(entwurf).name
        ziel.write_bytes(Path(entwurf).read_bytes())
        st.info(f"Vorschau des Entwurfs **{ziel.name}**")
        if st.button("Vorschau schließen", key="muster_entwurf_schliessen"):
            del st.session_state["muster_entwurf"]
            st.rerun()
    else:
        return

    try:
        bericht = musterlastenheft_lesen(ziel)
    except StandardImportFehler as e:
        st.error(str(e))
        return

    st.info(f"**{bericht.anzahl} Kriterien erkannt.**")

    feld = bericht.anwendungsfeld
    if feld is not None:
        korpus = f"{feld.korpus} Lastenhefte" if feld.korpus else "unbekannt"
        st.markdown(
            f"**Anwendungsfeld:** {feld.gegenstand_mehrzahl} · **Korpus:** {korpus}",
            help=None if feld.korpusbefunde else
            "Anderes Feld als das gemessene: Häufigkeitsangaben und Beispiele aus dem "
            "Druckguss-Korpus entfallen im Prompt. Die dokumentierten Trefferquoten "
            "gelten hier nicht.")

    # Kritisches nicht in eine Klappliste: Hier stimmt eine Grundlage nicht,
    # und das Ergebnis sähe trotzdem normal aus.
    for k in bericht.kritisch:
        st.warning(k)

    if bericht.warnungen:
        with st.expander(f"⚠️  {len(bericht.warnungen)} Hinweis(e) zum Dokument",
                         expanded=False):
            for w in bericht.warnungen[:15]:
                st.markdown(f"- {w}")
            if len(bericht.warnungen) > 15:
                st.caption(f"… und {len(bericht.warnungen) - 15} weitere.")

    vorgabe = feld.gegenstand_mehrzahl if feld is not None else ziel.stem
    name = (st.text_input("Name", value=vorgabe, key="muster_name",
                          help="Unter diesem Namen hinterlegt. Ein vorhandener Name "
                               "ersetzt dessen Fassung; Praxisarchiv und Ablageordner "
                               "bleiben erhalten.") or vorgabe).strip()
    bestand = next((e for e in bibliothek.eintraege()
                    if e.schluessel == bibliothek.schluessel_fuer(name)), None)

    if bestand is None:
        st.caption("Neu — noch nicht hinterlegt.")
    else:
        d = vergleiche_mit_bestand(bericht.kriterien,
                                   bestand.ordner / "Standard_Lastenheft_Chunks.jsonl")
        st.markdown(f"**Gegenüber „{bestand.name}“**",
                    help="Vergleich mit der hinterlegten Fassung gleichen Namens.")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Neu", len(d["neu"]))
        c2.metric("Geändert", len(d["geaendert"]))
        c3.metric("Entfallen", len(d["entfallen"]))
        c4.metric("Unverändert", len(d["unveraendert"]))
        for titel, liste in (("Neue Kriterien", d["neu"]),
                             ("Geänderte Kriterien", d["geaendert"]),
                             ("Entfallene Kriterien", d["entfallen"])):
            if liste:
                with st.expander(f"{titel} ({len(liste)})", expanded=False):
                    for x in liste:
                        st.markdown(f"- {x}")
        if d["neu"] or d["entfallen"]:
            st.warning("Die Zahl der Kriterien ändert sich — frühere Kennzahlen sind "
                       "nicht mehr direkt vergleichbar.")

    aktivieren = st.checkbox("Danach aktivieren", value=True, key="muster_aktivieren")
    if st.button("Hinterlegen", type="primary", key="muster_uebernehmen"):
        e = bibliothek.hinterlegen(name, bericht.kriterien, bericht.anwendungsfeld,
                                   ziel, aktivieren_danach=aktivieren)
        st.session_state.pop("muster_entwurf", None)
        st.session_state.pop("muster_aktiv", None)
        st.success(f"„{e.name}“ hinterlegt{' und aktiv' if e.aktiv else ''}.")
        st.rerun()


# ── Praxisarchiv ───────────────────────────────────────────────────────────
def _lade_archiv() -> Praxisarchiv | None:
    """Archiv laden, ohne dass ein fehlendes Archiv die Prüfung stoppt."""
    try:
        return Praxisarchiv()
    except FileNotFoundError:
        return None


def _render_praxisarchiv() -> None:
    """Historische Lastenhefte einlesen und durchsuchbar machen."""
    aktiv = bibliothek.aktiver()
    st.markdown(f"**Praxisarchiv{f' · {aktiv.name}' if aktiv else ''}**",
                help="Frühere Kundenlastenhefte. Sie ändern keine Einstufung, sondern "
                     "zeigen, wie andere Kunden denselben Punkt formuliert haben. Jedes "
                     "Musterlastenheft hat sein eigenes Archiv.")

    info = archiv_info()
    if info:
        st.success(f"**{len(info['dokumente'])} Lastenhefte** · {info['abschnitte']} "
                   f"Abschnitte · {info['erstellt']}")
        with st.expander("Enthaltene Dokumente", expanded=False):
            st.markdown(", ".join(info["dokumente"]))
            for u in info.get("uebersprungen") or []:
                st.caption(f"übersprungen — {u}")
    else:
        st.info("Noch kein Archiv — die Prüfung läuft auch ohne.")

    historie = bibliothek.historie_ordner()
    hochgeladen = st.file_uploader("Frühere Lastenhefte hinzufügen",
                                   type=UPLOAD_TYPES, accept_multiple_files=True,
                                   key="praxis_upload")
    if hochgeladen:
        for f in hochgeladen:
            (historie / f.name).write_bytes(f.getvalue())
        st.success(f"{len(hochgeladen)} Datei(en) abgelegt.")

    vorhanden = sorted(p for p in historie.iterdir()
                       if p.is_file() and p.suffix.lower() in
                       {f".{t}" for t in UPLOAD_TYPES})
    if not vorhanden:
        # Ein Archiv kann auch über die Kommandozeile aus einem anderen Ordner
        # gebaut sein — dann ist der Ablageordner leer, das Archiv aber nicht.
        quelle = (info or {}).get("quelle")
        st.caption("Ablageordner leer."
                   + (f" Das vorhandene Archiv stammt aus {quelle}." if quelle else ""),
                   help=str(historie))
        return

    ids = korpus_ids()
    im_korpus = [p for p in vorhanden if p.stem in ids]
    st.markdown(f"**{len(vorhanden)} Datei(en) im Ablageordner**",
                help=", ".join(p.name for p in vorhanden[:40]))

    # Das Musterlastenheft darf nicht ins Erfahrungsarchiv: Es ist der Maßstab
    # und würde jede Forderung mit sich selbst belegen.
    nur_korpus = st.checkbox(
        "Nur Lastenhefte aus dem Korpus des Musterlastenhefts",
        value=bool(im_korpus),
        help="Hält das Musterlastenheft und fremde Dokumente heraus. "
             f"Trifft auf {len(im_korpus)} von {len(vorhanden)} Dateien zu.",
        key="praxis_nur_korpus")
    if nur_korpus and not im_korpus:
        st.warning("Keine Datei gehört zum Korpus — das Archiv bliebe leer.")

    if st.button("Archiv aufbauen", type="primary", key="praxis_bauen",
                 disabled=nur_korpus and not im_korpus):
        fortschritt = st.progress(0.0, text="Lese Dokumente…")

        def on_progress(i: int, n: int, name: str):
            fortschritt.progress(min(i / n, 1.0), text=f"{i} von {n} — {name}")

        try:
            b = baue_archiv(historie,
                            erlaubte_ids=ids if nur_korpus else None,
                            progress_callback=on_progress)
        except (FileNotFoundError, ValueError) as e:
            st.error(str(e))
            return
        finally:
            fortschritt.empty()

        # Gleich in den Eintrag sichern, nicht erst beim nächsten Wechsel.
        bibliothek.zuruecksichern()
        st.success(f"{len(b.dokumente)} Lastenhefte, {b.abschnitte} Abschnitte "
                   f"in {b.dauer_s:.0f} s.")
        for u in b.uebersprungen:
            st.caption(f"übersprungen — {u}")
        st.rerun()


def _render_guete(statistik: dict, abschnitte: int) -> None:
    """Zeigt, wie gut das Dokument zur Gliederung passt.

    Steht ganz oben im Ergebnis, weil es die Lesart aller folgenden Zahlen
    bestimmt: Bei schwer erschließbaren Dokumenten findet die Suche deutlich weniger
    Belegstellen, und der Bericht sieht trotzdem aus wie jeder andere.
    """
    from src.pruefung.dokumentguete import aus_statistik

    g = aus_statistik(statistik, abschnitte)
    if g is None:
        return
    if g.warnen:
        st.warning(g.text)
    else:
        # Der Text trägt Markdown-Fett. Innerhalb eines HTML-Blocks wertet
        # Streamlit kein Markdown aus, deshalb hier von Hand nach <strong>.
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", _html.escape(g.text))
        st.markdown(
            f'<div class="guete {g.stufe}"><span class="wert">{g.wert:.2f}</span>'
            f'<span>{text}</span></div>', unsafe_allow_html=True)


def _render_laufbedingungen(ergebnis: dict) -> None:
    """Womit ist der Bericht entstanden — und lief der Entscheider mit?

    Der Entscheider hebt die Trefferquote spürbar. Nach einem neuen
    Import des Musterlastenhefts gehört er nicht mehr dazu und bleibt aus; bisher
    stand das nur im Rohergebnis. Deshalb eine Warnung, wenn er nicht lief, und
    die übrigen Bedingungen zum Nachschlagen.
    """
    from src.pruefung import entscheider as EN
    from src.pruefung.steckbrief import laufbedingungen

    stand, grund = EN.zustand(ergebnis)
    if stand == "nicht_aktiv":
        st.warning(
            f"**Entscheider nicht aktiv** — {grund}. Ohne ihn bleiben mehr Punkte "
            f"fälschlich auf „keine Vorgabe“. "
            f"Abhilfe: `python main.py kalibrieren <Ordner mit den bewerteten "
            f"Lastenheften>`.")
    elif stand == "aktiv" and "übernommen" in grund:
        st.info(f"**Entscheider übertragen** — {grund}. Die statistisch gehobenen Punkte "
                f"sind hier weniger abgesichert als beim Musterlastenheft, für das er "
                f"trainiert wurde.")
    zeilen = laufbedingungen(ergebnis)
    if zeilen:
        with st.expander("Laufbedingungen", expanded=False):
            st.markdown("\n".join(f"- **{_html.escape(k)}:** {_html.escape(v)}"
                                  for k, v in zeilen))


def _render_hinweise(ergebnis: dict, kriterien: list[dict]) -> None:
    """Festlegungen an Punkten, die das Musterlastenheft offen lässt.

    Kein Status, keine Kennzahl. Der Wortlaut ist entsprechend zurückhaltend:
    Nicht jeder Hinweis trifft eine Abweichung. Als
    Behauptung wäre das zu wenig, als Lesehilfe genug — aber nur, wenn die
    Oberfläche nicht so tut, als stünde hier ein Befund.
    """
    hinweise = ergebnis.get("hinweise") or []
    if not hinweise:
        return

    titel = {k["nr"]: k["titel"] for k in kriterien}
    st.divider()
    st.markdown(f"#### 🔎  {len(hinweise)} Stelle(n) für den fachlichen Blick",
                help="Das Musterlastenheft lässt diese Punkte offen, dieses Lastenheft "
                     "legt sie fest. Keine Abweichung und kein Fehler — aber eine "
                     "Festlegung, die Geld kosten kann. Etwa jeder siebte bis zehnte "
                     "Hinweis trifft eine Abweichung.")

    for h in hinweise:
        nr = h.get("nr", "")
        # Zwei Herkünfte, zwei Verlässlichkeiten. Der Modelldurchgang liest das
        # Kundendokument; der Detektor liest die Begründung, die die Prüfung
        # selbst geschrieben hat. Wer den Hinweis einschätzen will, muss das
        # unterscheiden können — deshalb steht die Herkunft dran und nicht nur
        # der Befund.
        aus_begruendung = h.get("art") == "Erzeugniswahl"
        with st.expander(f"**{nr}** {titel.get(nr, '')} · Seite "
                         f"{h.get('fundstelle', '—').lstrip('S')}", expanded=False):
            if aus_begruendung:
                st.markdown(f"**Die Prüfung hat hier notiert:** {h.get('text', '')}")
            else:
                st.markdown(f"**Im Lastenheft:** {h.get('text', '')}")
            if h.get("offene_stelle"):
                st.caption(h["offene_stelle"] if aus_begruendung
                           else f"Das Musterlastenheft sagt hier: "
                                f"{h['offene_stelle']}")


def _render_praxisbefunde(befunde: list) -> None:
    """Einordnung gegenüber dem Korpus als Ganzes, im Prüfergebnis.

    Der Vergleich mit einem EINZELNEN früheren Lastenheft ist die zweite
    Funktion und steht in _render_vergleich().
    """
    z = zusammenfassung(befunde)
    st.markdown(f"**Einordnung gegenüber der Praxis** · {z['korpus']} frühere Lastenhefte",
                help="Häufigkeit ist keine Bewertung und sagt keine "
                     "Abweichung voraus. Sie zeigt, wo ein Blick ins Archiv lohnt.")

    p1, p2, p3 = st.columns(3)
    p1.metric("Lücken gegenüber der Praxis", z["luecke"],
              help="Der Kunde regelt einen Punkt nicht, den fast alle früheren "
                   "Kunden geregelt haben. Kein Mangel — ein offener Punkt.")
    p2.metric("Selten im Korpus", z["selten"],
              help="Forderungen, für die es kaum Erfahrungswerte gibt.")
    p3.metric("Üblich", z["ueblich"],
              help="Punkte, die die große Mehrheit der früheren Kunden ebenso regelt.")

    auffaellig = [b for b in befunde if b.auffaellig]
    if not auffaellig:
        st.caption("Keine Auffälligkeiten.")
        return

    for b in auffaellig:
        marke = "🟠" if b.einordnung == "luecke" else "🔎"
        with st.expander(f"{marke} **{b.nr}** {b.titel} — {LABEL[b.einordnung]} "
                         f"({b.n_geregelt} von {b.korpus})", expanded=False):
            st.markdown(b.hinweis)
            for j, s in enumerate(b.stellen):
                st.caption(f"{s.lh_id}, Seite {s.seite} · "
                           f"Relevanz {s.score * 100:.0f} %")
                st.text_area("Stelle", value=s.text, height=110, disabled=True,
                             label_visibility="collapsed",
                             key=f"praxis_{b.nr}_{j}")
            if not b.stellen:
                st.caption("Keine passende Belegstelle.")


# ── Prüflauf ───────────────────────────────────────────────────────────────
# Die vier Status tragen ihren Schweregrad über Tonwert und Form, nicht über
# Farbton — kein Rot, kein Grün. Zwei Gründe: Rot-Grün ist für einen Teil der
# Nutzer nicht unterscheidbar, und Prüfberichte werden ausgedruckt, oft in
# Graustufen. A ist deshalb das einzige voll gefüllte Etikett.
#
# STATUS_ICON bleibt für die wenigen Stellen, die kein HTML rendern können
# (Beschriftungen von Expandern und Auswahlfeldern). Dort steht ein Zeichen
# derselben Reihe: leer, halb, voll, Umriss.
STATUS_ICON = {"E": "▫", "T": "◐", "A": "◼", "N": "○"}
STATUS_TEXT = DESIGN_STATUS_TEXT


def _dokument_laden(uploaded_new):
    """Hochgeladenes Lastenheft einlesen. Gibt None zurück und meldet den Grund.

    Von beiden Funktionen genutzt — Prüfung und Praxisabgleich lesen dasselbe
    Dokument auf dieselbe Weise.
    """
    suffix = Path(uploaded_new.name).suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_new.getvalue())
        tmp_path = Path(tmp.name)

    try:
        new_chunks = load_document(tmp_path, kind="neu")
    except TextExtraktionsFehler as e:
        st.error(str(e))
        return None
    finally:
        tmp_path.unlink(missing_ok=True)

    for c in new_chunks:
        c.source_file = uploaded_new.name

    if not new_chunks:
        st.error("Aus diesem Dokument konnte kein Text gelesen werden.")
        return None

    ocr_ok, ocr_meldung = ocr_status()
    if not ocr_ok:
        st.warning(f"OCR nicht verfügbar — gescannte Seiten bleiben unberücksichtigt. "
                   f"{ocr_meldung}")
    return new_chunks


ART_ICON = {"beide": "🟢", "nur_neu": "🔵", "nur_historisch": "🟠", "keiner": "○"}


def _run_praxisvergleich(uploaded_new, min_similarity: float) -> None:
    """Zweite Funktion: ähnlichste frühere Lastenhefte suchen.

    Ohne Bezug zum Musterlastenheft und ohne Prüflauf. Die Rangliste entsteht
    allein aus dem Textvergleich der Dokumente; der Abschnittsvergleich mit dem
    Sprachmodell folgt auf Knopfdruck für ein gewähltes Dokument.
    """
    archiv = _lade_archiv()
    if archiv is None:
        st.error("Kein Praxisarchiv — im Reiter „Praxisarchiv“ aufbauen.")
        return

    new_chunks = _dokument_laden(uploaded_new)
    if new_chunks is None:
        return

    stem = Path(uploaded_new.name).stem
    with st.spinner("Suche die ähnlichsten früheren Lastenhefte…"):
        brauchbar = [c for c in new_chunks if not DV.ist_schrott(c.text)]
        neu_norm = DV._neue_embeddings(brauchbar)
        rang = DV.rangliste(brauchbar, archiv, neu_norm=neu_norm, ohne=stem)

    if not rang:
        st.error("Das Praxisarchiv enthält kein Dokument zum Vergleichen.")
        return

    # Für die spätere Auswahl merken: Der Abschnittsvergleich soll ohne neuen
    # Suchlauf auskommen, wenn nur das Vergleichsdokument gewechselt wird.
    st.session_state["dv"] = {
        "name": uploaded_new.name, "chunks": brauchbar, "neu_norm": neu_norm,
        "rang": rang, "gesamt": len(new_chunks), "vergleiche": {},
    }


def _render_dokumentvergleich(selected_model: str) -> None:
    """Rangliste, Auswahl und Abschnittsvergleich gegen ein einzelnes Dokument."""
    dv = st.session_state.get("dv")
    if not dv:
        return

    archiv = _lade_archiv()
    if archiv is None:
        return

    rang = dv["rang"]
    st.divider()
    st.markdown(f"**Ähnlichste frühere Lastenhefte zu {dv['name']}**",
                help=f"{len(dv['chunks'])} verwertbare Abschnitte gegen {len(archiv)} "
                     f"Abschnitte aus {len(archiv.dokumente)} früheren Lastenheften. Die "
                     f"Reihenfolge ist ein Vorschlag. Das Vergleichsdokument ist frei wählbar. "
                     f"Der Rangwert "
                     f"ordnet nur; er ist keine Ähnlichkeit in Prozent.")

    st.dataframe(
        [{"Lastenheft": d.lh_id,
          "Rangwert": f"{d.wert:.3f}",
          "vergleichbare Abschnitte": d.vergleichbar,
          "Umfang": d.abschnitte} for d in rang[:10]],
        use_container_width=True, hide_index=True)

    namen = [d.lh_id for d in rang]
    gewaehlt = st.selectbox(
        "Abschnittsvergleich gegen", namen, index=0, key="dv_wahl",
        format_func=lambda n: f"{n} — Rangwert "
                              f"{next(d for d in rang if d.lh_id == n).wert:.3f}, "
                              f"{next(d for d in rang if d.lh_id == n).vergleichbar} "
                              f"vergleichbare Abschnitte")

    if st.button(f"Abschnitte gegen {gewaehlt} vergleichen", type="primary",
                 key="dv_paare_btn"):
        paare, vergleichbar = DV.abschnittspaare(
            dv["chunks"], archiv, gewaehlt, neu_norm=dv["neu_norm"])
        if not paare:
            st.session_state["dv"]["vergleiche"][gewaehlt] = None
        else:
            fortschritt = st.progress(0.0, text="Vergleiche Abschnitte…")

            def on_progress(i, n, label):
                fortschritt.progress(min(i / n, 1.0),
                                     text=f"Abschnitt {i} von {n} — {label}")

            try:
                DV.vergleiche_abschnitte(paare, gewaehlt, model=selected_model,
                                         progress_callback=on_progress)
            finally:
                fortschritt.empty()
            st.session_state["dv"]["vergleiche"][gewaehlt] = DV.auswerten(
                paare, vergleichbar, gewaehlt, len(dv["chunks"]))

    if gewaehlt not in dv["vergleiche"]:
        st.caption("Noch nicht verglichen.",
                   help="Der Abschnittsvergleich braucht das Sprachmodell und dauert "
                        "einige Sekunden.")
        return

    erg = dv["vergleiche"][gewaehlt]
    if erg is None:
        st.warning(f"**Keine vergleichbaren Abschnitte mit {gewaehlt}.** Ein anderes "
                   f"Dokument aus der Liste versuchen.")
        return

    _render_dv_ergebnis(erg, gewaehlt, dv["name"])


BEWERTUNG_ICON = {"identisch": "🟢", "aehnlich": "🔵",
                  "abweichend": "🟠", "kein_bezug": "○"}
BEWERTUNG_TEXT = {"identisch": "gleiche Anforderung", "aehnlich": "ähnlich",
                  "abweichend": "abweichend", "kein_bezug": "kein Bezug"}


def _render_dv_ergebnis(erg, gewaehlt: str, name: str) -> None:
    z = DV.zusammenfassung(erg)
    bewertet = len(erg.paare) - erg.nicht_bewertet

    st.markdown(f"**Abschnittsvergleich {name} gegen {gewaehlt}**")

    c1, c2 = st.columns(2)
    wert = ("keine Aussage" if erg.uebereinstimmung is None
            else f"{erg.uebereinstimmung:.0%}")
    c1.metric("Ähnlichkeit der vergleichbaren Stellen", wert,
              help="Mittel der Einzelurteile des Sprachmodells über die "
                   "verglichenen Abschnittspaare.")
    c2.metric("Vergleichbare Abschnitte",
              f"{erg.vergleichbar} von {erg.abschnitte_neu}",
              help="Abschnitte dieses Lastenhefts, die im früheren überhaupt "
                   "ein Gegenstück haben.")

    # Die Basis gehört neben die Zahl, nicht in eine Fußnote.
    if erg.uebereinstimmung is None:
        st.info("**Keine Aussage:** Kein Abschnittspaar ließ sich bewerten.")
    else:
        st.info(f"**{wert} beruht auf {bewertet} verglichenen "
                f"Stellen**, nicht auf allen {erg.abschnitte_neu} Abschnitten — ein Wert "
                f"über diese Stellen, nicht über das ganze Dokument.")

    if erg.nicht_bewertet:
        st.warning(f"{erg.nicht_bewertet} Paar(e) ohne verwertbare Modellantwort — "
                   f"nicht im Wert enthalten.")

    verteilung = " · ".join(f"{BEWERTUNG_ICON[b]} {BEWERTUNG_TEXT[b]} {z[b]}"
                            for b in DV.BEWERTUNGEN if z[b])
    if verteilung:
        st.caption(verteilung)

    # Schlüssel über die laufende Nummer: Mehrere Abschnitte derselben Seite
    # ergäben sonst dieselbe Kennung, und Streamlit bricht die Seite ab.
    for n, p in enumerate(sorted(erg.paare,
                                 key=lambda x: (x.wert if x.wert is not None else -1))):
        wert = f"{p.wert} %" if p.wert is not None else "—"
        kopf = (f"{BEWERTUNG_ICON[p.bewertung]} **{wert}** · Seite {p.seite_neu} "
                f"gegen {gewaehlt} Seite {p.seite_alt}")
        with st.expander(kopf, expanded=False):
            if p.fehler:
                st.error(p.fehler)
            elif p.unterschied:
                st.markdown(f"**Unterschied:** {p.unterschied}")
            links, rechts = st.columns(2)
            with links:
                st.markdown(f"**{name}** · Seite {p.seite_neu}")
                st.text_area("hier", value=p.text_neu, height=180, disabled=True,
                             label_visibility="collapsed",
                             key=f"dv_neu_{gewaehlt}_{n}")
            with rechts:
                st.markdown(f"**{gewaehlt}** · Seite {p.seite_alt}")
                st.text_area("dort", value=p.text_alt, height=180, disabled=True,
                             label_visibility="collapsed",
                             key=f"dv_alt_{gewaehlt}_{n}")


def _run_pruefung(uploaded_new, selected_model: str,
                  min_similarity: float, custom_prompt: str | None,
                  markierung: str = "gruendlich") -> None:
    """Erste Funktion: Prüfung entlang der Kriterien des Musterlastenhefts.

    Läuft als eigener Prozess (src/pruefung/auftrag.py). Vorher lief sie im
    Streamlit-Skript, und jede Bedienung während der 10 bis 20 Minuten brach sie
    ohne Meldung ab. Die Seite zeigt jetzt nur den Fortschritt und darf neu
    aufgebaut oder geschlossen werden.
    """
    auftrag = A.anlegen(uploaded_new.name, uploaded_new.getvalue(), {
        "modell": selected_model, "min_score": min_similarity,
        "custom_prompt": custom_prompt, "markierung": markierung})
    st.session_state.pop("pruefung", None)
    st.session_state["auftrag"] = str(auftrag.ordner)
    _starten(auftrag)
    _render_auftrag()


# Startet den Auftrag als eigenen Prozess. Die Tests ersetzen das durch
# A.ausfuehren, damit die Attrappe des Sprachmodells im selben Prozess greift.
_starten = A.starten


def _uebernehmen(auftrag) -> bool:
    """Das Ergebnis eines fertigen Auftrags als aktuelle Prüfung in die Sitzung."""
    daten = A.ergebnis_laden(auftrag)
    if daten is None:
        return False
    # Streamlit baut die Seite bei JEDER Bedienung neu auf — auch beim Klick auf
    # „Excel herunterladen" oder „Nachvollziehen". Deshalb liegt der Bericht in
    # der Sitzung, und Praxisabgleich und Excel werden einmal gerechnet.
    st.session_state["pruefung"] = {
        "datei": daten.get("datei") or auftrag.name, "ergebnis": daten["ergebnis"],
        "details": daten.get("details") or {},
        "kriterien": daten.get("kriterien") or load_kriterien(),
        "statistik": daten.get("statistik") or {},
        "abschnitte": daten.get("abschnitte") or 0,
        "stem": daten.get("stem") or auftrag.name, "auftrag": auftrag.name,
    }
    return True


def _auftrag_anzeigen(ordner: str) -> None:
    """Fortschritt eines laufenden Auftrags. Läuft als Fragment und liest alle
    zwei Sekunden neu, ohne den Rest der Seite anzufassen."""
    auftrag = A.Auftrag(Path(ordner))
    z = A.zustand(auftrag)
    e = auftrag.lesen(auftrag.einstellungen, {}) or {}
    datei = e.get("datei") or auftrag.name

    if z["laeuft"]:
        gesamt = max(int(z.get("gesamt") or 1), 1)
        st.progress(min(int(z.get("schritt") or 0) / gesamt, 1.0),
                    text=f"**{datei}** · {z.get('text') or 'läuft …'}")
        links, rechts = st.columns([4, 1])
        links.caption("Die Prüfung läuft im Hintergrund weiter — die Seite darf "
                      "bedient, neu geladen oder geschlossen werden.")
        if rechts.button("Abbrechen", key="auftrag_abbrechen"):
            A.abbrechen(auftrag)
            st.rerun(scope="app")
        return

    if z["zustand"] == "fertig" and _uebernehmen(auftrag):
        st.session_state.pop("auftrag", None)
        st.rerun(scope="app")
        return

    grund = z.get("fehler") or "Kein Ergebnis."
    (st.info if z["zustand"] == "abgebrochen" else st.error)(
        f"**Prüfung von {datei} {'abgebrochen' if z['zustand'] == 'abgebrochen' else 'fehlgeschlagen'}.** "
        f"{grund}")
    if st.button("Schließen", key="auftrag_schliessen"):
        st.session_state.pop("auftrag", None)
        st.rerun(scope="app")


def _render_auftrag() -> None:
    ordner = st.session_state.get("auftrag")
    if not ordner:
        return
    laeuft = A.zustand(A.Auftrag(Path(ordner)))["laeuft"]
    st.fragment(run_every=2 if laeuft else None)(_auftrag_anzeigen)(ordner)


def _render_verlauf() -> None:
    """Frühere Prüfungen wieder öffnen — ohne Neurechnung."""
    fertig = [a for a in A.liste(10) if a.ergebnis.exists()]
    if not fertig:
        return
    with st.expander(f"Frühere Prüfungen ({len(fertig)})", expanded=False):
        for a in fertig:
            e = a.lesen(a.einstellungen, {}) or {}
            angelegt = e.get("angelegt")
            wann = time.strftime("%d.%m.%Y %H:%M", time.localtime(angelegt)) if angelegt else "—"
            links, rechts = st.columns([4, 1])
            links.markdown(f"**{e.get('datei') or a.name}** · {wann} · "
                           f"{e.get('modell') or '—'} · Markierung "
                           f"{e.get('markierung') or '—'}")
            if rechts.button("Öffnen", key=f"verlauf_{a.name}"):
                if _uebernehmen(a):
                    st.rerun()
                else:
                    st.error("Das Ergebnis dieses Auftrags ist nicht lesbar.")
        st.caption(f"Abgelegt in {A.AUFTRAEGE_DIR} — enthält Auszüge aus den "
                   f"Kundenlastenheften und wird nicht versioniert.")


def _render_gespeicherte_pruefung() -> None:
    p = st.session_state.get("pruefung")
    if not p:
        return
    _render_bericht(p["ergebnis"], p["details"], p["kriterien"], p["statistik"],
                    p["abschnitte"], p["stem"], ablage=p)


def _render_bericht(ergebnis: dict, details: dict, kriterien: list[dict],
                    such_statistik: dict, abschnitte: int, stem: str,
                    ablage: dict | None = None) -> None:
    """Der Bericht zu einem Ergebnis — gerechnet oder abgespielt.

    Bewusst getrennt von _run_pruefung: Der Demo-Modus spielt ein
    gespeichertes Ergebnis ab und zeigt damit GENAU diese Anzeige, nicht
    eine nachgebaute. Was hier steht, gilt für beide Wege.

    `such_statistik` darf leer sein (dann entfällt die Güteanzeige),
    `abschnitte` ist die Zahl der Textabschnitte des Dokuments und `stem`
    der Dateiname ohne Endung für die Herunterladeknöpfe. `ablage` ist der
    Sitzungseintrag einer gespeicherten Prüfung; darin werden Praxisabgleich und
    Excel-Datei einmal gerechnet statt bei jedem Neuaufbau der Seite.
    """
    kz     = ergebnis["kennzahlen"]
    kje    = kennzahlen_je_einstufung(ergebnis, kriterien)
    fehler = validate(ergebnis, kriterien)
    offen  = nicht_bewertete(details)
    gruende = n_gruende(ergebnis, details)

    # Ein N aus der Retrieval-Schwelle ist keine Aussage über das Lastenheft,
    # sondern ein Hinweis auf das Dokument. Bei 30 Fundstellen und Schwelle 0,30
    # tritt der Fall fast nie ein — über alle 1.206 Testfälle zweimal. Wenn er
    # doch eintritt, liegt es am Text, nicht an der Einstellung.
    if gruende["ohne_kandidaten"]:
        st.warning(
            f"**{gruende['ohne_kandidaten']} Kriterien ungeprüft auf N** — keine "
            f"passende Textstelle gefunden. Meist schlecht erkannter Text (Scan, "
            f"Layout, Sprache); im Original nachsehen."
        )

    # Werkzeugversagen darf nicht als „Kunde gibt nichts vor" gelesen werden.
    if offen:
        st.error(
            f"**{len(offen)} von {len(kriterien)} Kriterien nicht bewertet** — das "
            f"Modell hat nicht verwertbar geantwortet. Das N dort ist KEINE Aussage "
            f"über das Lastenheft, die Kennzahlen sind nicht belastbar."
        )
        with st.expander(f"Gründe ({len(offen)})", expanded=len(offen) > len(kriterien) // 2):
            for nr, grund in offen[:20]:
                st.markdown(f"- **{nr}** — {grund}")
            if len(offen) > 20:
                st.caption(f"… und {len(offen) - 20} weitere mit gleichem Muster.")

    _render_guete(such_statistik, abschnitte)
    _render_laufbedingungen(ergebnis)

    st.divider()
    # Zwei Blöcke statt acht Zahlen nebeneinander: oben, wie die 67 Kriterien
    # ausgehen; unten, was das im Verhältnis bedeutet. Ohne Überschrift stand
    # eine Absolutzahl neben einer Quote, als wäre es dasselbe.
    st.markdown(_kapitel_html(f"Verteilung über die {len(kriterien)} Kriterien"),
                unsafe_allow_html=True)
    kennzahlenreihe([
        ("Entspricht",   kz["entspricht"],    "E — verbindlich geregelt, kein Widerspruch"),
        ("Teilweise",    kz["teilweise"],     "T — nur gestreift oder unverbindlich"),
        ("Abweichung",   kz["abweichung"],    "A — laut Modell anders geregelt als im "
                                              "Musterlastenheft"),
        ("Ohne Vorgabe", kz["keine_vorgabe"], "N — der Kunde sagt dazu nichts"),
        # Getrennt von den vier Status: Die Markierung hebt Verdachtsfälle zur
        # Durchsicht auf A, die Verteilung links zählt sie unter dem Urteil des Modells.
        ("Zur Durchsicht markiert", kz.get("markiert", 0),
         "Stellen mit Anzeichen einer Abweichung (Kostenfolge, Widerspruch, …). In der "
         "Liste als A geführt, in Verteilung und Quoten unter dem Urteil des Modells "
         "gezählt — die meisten erweisen sich bei der Durchsicht als unbedenklich."),
    ])

    def _pct(v):
        return "—" if v is None else f"{v * 100:.1f} %".replace(".", ",")

    st.markdown(_kapitel_html("Kennzahlen"), unsafe_allow_html=True)
    kennzahlenreihe([
        ("Abweichungsquote", _pct(kz["abweichungsquote"]),
         "(A + 0,5 × T) / geregelt. N fällt aus dem Nenner heraus."),
        ("Abdeckungsquote", _pct(kz["abdeckungsquote"]),
         f"geregelt / {len(kriterien)} — wie viel des Standards das Lastenheft "
         f"überhaupt regelt."),
        ("Konformitätsquote", _pct(kz["konformitaetsquote"]),
         "E / geregelt"),
        ("Pflicht ohne Vorgabe", kje["Pflicht"]["N"],
         "Vom Fachbereich zu klären — kein Mangel des Lieferanten."),
    ])

    if fehler:
        with st.expander(f"⚠️  Strukturprüfung: {len(fehler)} Hinweis(e)", expanded=False):
            for f in fehler:
                st.markdown(f"- {f}")

    st.divider()

    # Das Ergebnis merken — der Vergleich gegen frühere Lastenhefte braucht
    # die Einstufungen als eigene Seite des Vergleichs.
    st.session_state["letzte_pruefung"] = ergebnis
    # Der Mitschnitt muss die Sitzung überleben: Die Auswahlliste in der
    # Nachvollziehen-Ansicht löst einen Neuaufbau der Seite aus, und dabei ist
    # jede lokale Variable weg. Ohne das wäre die Ansicht beim ersten Klick leer.
    st.session_state["letzte_details"] = details

    # Häufigkeit im Korpus und Lücken: braucht die Einstufungen, kostet
    # Sekunden und gehört deshalb hierher, nicht in den Vergleich.
    if ablage is not None and "excel" in ablage:
        befunde, excel = ablage["befunde"], ablage["excel"]
    else:
        archiv  = _lade_archiv()
        befunde = None
        if archiv:
            with st.spinner("Vergleiche mit der Praxis…"):
                befunde = praxisabgleich(ergebnis, archiv=archiv, kriterien=kriterien,
                                         ohne_dokument=stem)
        excel = generate_excel(ergebnis, details, kriterien,
                               basis="Standard_Lastenheft_Chunks.jsonl",
                               praxis=befunde)
        if ablage is not None:
            ablage["befunde"], ablage["excel"] = befunde, excel
    d1, d2 = st.columns([3, 2])
    d1.download_button(
        "📥  Prüfbericht als Excel herunterladen",
        data=excel,
        file_name=f"{stem}_pruefbericht.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )
    d2.download_button(
        "⬇  Rohergebnis (JSON)",
        data=json.dumps(ergebnis, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name=f"{stem}_bewertung.json",
        mime="application/json",
        use_container_width=True,
    )

    # Steht bewusst VOR der Liste der 67 Kriterien: Das ist der Teil, wegen
    # dem jemand den Bericht öffnet. Die Einstufungen kann man danach lesen.
    _render_hinweise(ergebnis, kriterien)

    if befunde:
        st.divider()
        _render_praxisbefunde(befunde)

    # ── Ergebnis je Kapitel ───────────────────────────────────────────────
    #
    # Die ganze Liste wird in EINEM Aufruf gerendert. Vorher war es ein
    # Streamlit-Element je Kriterium — 67 Stück, jedes mit eigenem Rahmen und
    # eigenen Abständen. Als ein Block hält das Raster, und das Aufklappen
    # kostet keinen Serverdurchlauf mehr.
    st.divider()
    st.markdown("#### Ergebnis je Kriterium")

    teile: list[str] = []
    letztes_kapitel = None
    for k in kriterien:
        if k["kapitel"] != letztes_kapitel:
            letztes_kapitel = k["kapitel"]
            teile.append(_kapitel_html(k["kapitel"]))

        b      = ergebnis["bewertungen"].get(k["nr"], {})
        status = b.get("status", "N")
        kand   = (details.get(k["nr"]) or {}).get("kandidaten") or []

        teile.append(kriterium_block(
            status, k["nr"], k["titel"], k["einstufung"],
            begruendung=b.get("begruendung", "") if status != "N" else "",
            fundstelle=b.get("fundstelle", "") if status != "N" else "",
            herkunft=b.get("herkunft"), status_modell=b.get("status_modell"),
            statistisch=bool(b.get("gehoben")),
            # Auch bei Status N die gefundenen Stellen zeigen: Gerade dort
            # ist die Frage „hat die Software etwas übersehen?" die wichtigste,
            # und ohne die Stellen ist sie nicht zu beantworten.
            stellen=kand[:3],
        ))

    st.markdown("".join(teile), unsafe_allow_html=True)

    if ergebnis["zusatzanforderungen"]:
        st.divider()
        with st.expander(f"➕  Zusatzanforderungen "
                         f"({len(ergebnis['zusatzanforderungen'])})", expanded=False):
            for z in ergebnis["zusatzanforderungen"]:
                st.markdown(f"- {z}")

    # ── Nachvollziehen ────────────────────────────────────────────────────
    # Steht bewusst ganz unten und zugeklappt: Für den Regelfall — jemand
    # liest den Bericht — ist es Ballast. Gebraucht wird es genau dann, wenn
    # eine Einstufung nicht einleuchtet, und dann sucht man danach.
    #
    # Ein Schalter statt eines Expanders, und zwar zwingend: Die Spur-Ansicht
    # öffnet für jede Station selbst einen Expander, und Streamlit verbietet
    # Expander in Expandern („Expanders may not be nested inside other
    # expanders“). Der Fehler trat erst beim Aufklappen auf, weil Streamlit den
    # Inhalt eines zugeklappten Expanders gar nicht erst durchläuft.
    st.divider()
    if st.toggle("🔍  Nachvollziehen — wie kam eine Einstufung zustande?",
                 value=False, key="spur_offen"):
        spur_kopf()
        render_spur(details, kriterien, ergebnis)



# ── Haupt-Render-Funktion ──────────────────────────────────────────────────
def render(selected_model: str, min_similarity: float,
           custom_prompt: str | None = None, startklar: bool = True):

    tab_compare, tab_muster, tab_praxis = st.tabs(
        ["Prüfung", "Musterlastenheft", "Praxisarchiv"])

    # ══════════════════════════════════════════════════════════════════════
    # TAB 1 — PRÜFUNG
    # ══════════════════════════════════════════════════════════════════════
    with tab_compare:
        kriterien = load_kriterien()

        # Nach einem Neuladen der Seite ist die Sitzung leer, ein gestarteter
        # Auftrag läuft aber weiter: wieder anhängen statt ihn zu verlieren.
        if not st.session_state.get("auftrag") and not st.session_state.get("pruefung"):
            laufend = A.laufender()
            if laufend is not None:
                st.session_state["auftrag"] = str(laufend.ordner)
        auftrag_laeuft = bool(st.session_state.get("auftrag")) and A.zustand(
            A.Auftrag(Path(st.session_state["auftrag"])))["laeuft"]

        uploaded_new = st.file_uploader(
            "Kundenlastenheft hochladen", type=UPLOAD_TYPES, key="lh_new_upload",
            help="PDF oder Word. Gescannte Seiten werden per Texterkennung gelesen.")

        st.divider()

        # Zwei getrennte Funktionen mit verschiedenen Fragen, verschiedenen
        # Quellen und sehr verschiedener Laufzeit. Sie in einen Knopf zu legen
        # hieße, jemanden minutenlang warten zu lassen, der nur nachschlagen
        # wollte, wie andere Kunden einen Punkt formuliert haben.
        archiv_da = archiv_info() is not None

        links, rechts = st.columns(2)

        # Umrandete Karten statt bloßer Spalten: Dass es zwei getrennte
        # Funktionen mit sehr verschiedener Laufzeit sind, muss man sehen
        # können, bevor man klickt — nicht erst beim Warten.
        with links, st.container(border=True):
            karte()
            aktiv = bibliothek.aktiver()
            st.markdown("**1 · Gegen das Musterlastenheft**",
                        help=f"Vergibt je Kriterium E/T/A/N mit Begründung und Fundstelle. "
                             f"Ein Aufruf des Sprachmodells je Kriterium.")
            st.caption(f"{aktiv.name if aktiv else 'Musterlastenheft'} · "
                       f"{len(kriterien)} Kriterien · einige Minuten")
            from src.pruefung import markierung as MK
            stufen = list(MK.STUFEN)
            markierung = st.selectbox(
                "Abweichungen markieren", stufen, index=stufen.index(MK.VORGABE),
                format_func=lambda s: MK.STUFEN_TEXT[s], key="lh_markierung",
                help="Lieber eine Abweichung zu viel als eine übersehen"
                     + ". „Gezielt“ markiert Kostenfolgen für den Lieferanten, Werkstoffe, die das "
                       "Musterlastenheft nicht kennt, Stellen, die einer Zuständigkeit oder Erlaubnis "
                       "des Musterlastenhefts entgegenstehen, und Punkte, deren Begründung selbst "
                       "einen Widerspruch nennt. „Gründlich“ markiert zusätzlich "
                       "Punkte, deren Begründung Kosten, Fristen oder ausschließliche Pflichten nennt, "
                       "und je Dokument die 5 Kriterien, bei denen das Modell einer Abweichung am "
                       "nächsten war. "
                       "Herstellervorgaben und Forderungen, die viele Kunden gleich stellen, gelten "
                       "nicht als Abweichung.")
            if not startklar:
                st.info("Noch nicht startklar — siehe oben.")
            # Nur eine Prüfung zugleich: Zwei Läufe teilten sich Modell und Grafikkarte.
            pruefen = st.button("Prüfung starten", type="primary",
                                key="lh_compare_btn", use_container_width=True,
                                disabled=not (uploaded_new and startklar) or auftrag_laeuft,
                                help="Läuft bereits eine Prüfung, erst nach deren Ende."
                                     if auftrag_laeuft else None)

        with rechts, st.container(border=True):
            karte()
            st.markdown("**2 · Gegen ein früheres Lastenheft**",
                        help="Sucht die ähnlichsten früheren Lastenhefte im Praxisarchiv "
                             "und stellt vergleichbare Abschnitte gegenüber. Unabhängig "
                             "von der Prüfung; der Abschnittsvergleich folgt auf Knopfdruck.")
            st.caption("Rangliste in Sekunden")
            if not archiv_da:
                st.info("Kein Praxisarchiv — Reiter „Praxisarchiv“.")
            vergleichen = st.button(
                "Ähnliche suchen", key="lh_praxis_btn", use_container_width=True,
                disabled=not (uploaded_new and archiv_da))

        if pruefen:
            _run_pruefung(uploaded_new, selected_model, min_similarity,
                          custom_prompt, markierung)
        elif st.session_state.get("auftrag"):
            _render_auftrag()
        elif st.session_state.get("pruefung"):
            p = st.session_state["pruefung"]
            links, rechts = st.columns([4, 1])
            links.caption(f"Letzte Prüfung: **{p['datei']}**")
            if rechts.button("Schließen", key="pruefung_schliessen"):
                del st.session_state["pruefung"]
                st.rerun()
            _render_gespeicherte_pruefung()
        else:
            _render_verlauf()

        # ── Demo ──────────────────────────────────────────────────────────
        # Steht unter den beiden Knöpfen und nicht darüber: Der Regelfall ist
        # eine echte Prüfung. Gezeigt wird ein aufgezeichneter Lauf über ein
        # erfundenes Lastenheft — kein Modellaufruf, kein Kundendokument.
        # Nicht neben einem echten Bericht: Beide trügen dieselben Bedienelemente.
        if (demo.verfuegbar() and not st.session_state.get("pruefung")
                and not st.session_state.get("auftrag")):
            st.divider()
            if st.toggle("▶  Beispielbericht ansehen (ohne Prüfung)",
                         value=False, key="demo_an"):
                daten = demo.laden()
                if daten is None:
                    st.error("Der aufgezeichnete Lauf ist unlesbar. Mit "
                             "`demo/erzeuge_lauf.py` neu erzeugen.")
                else:
                    st.info(
                        f"**Aufgezeichneter Lauf — nichts wird berechnet.** "
                        f"{daten.get('quelle', '—')} (erfunden) · {daten.get('modell', '—')}"
                        f" · {daten.get('erzeugt', '—')}"
                    )
                    # Mit Ablage in der Sitzung, wie ein gerechneter Lauf: Ohne
                    # sie rechnete jeder Klick (Nachvollziehen, Kriterienwahl)
                    # Praxisabgleich und Excel neu — Sekunden je Bedienung.
                    ablage = st.session_state.setdefault("demo_ablage", {})
                    if ablage.get("erzeugt") != daten.get("erzeugt"):
                        ablage.clear()
                        ablage["erzeugt"] = daten.get("erzeugt")
                    _render_bericht(
                        daten["ergebnis"], daten["details"], kriterien,
                        such_statistik={}, abschnitte=demo.abschnitte(daten),
                        stem="Beispiel-Lastenheft", ablage=ablage)

        if vergleichen:
            _run_praxisvergleich(uploaded_new, min_similarity)

        # Steht ausserhalb des Knopfes: Die Auswahl des Vergleichsdokuments löst
        # einen Neulauf aus, das Ergebnis muss ihn überleben.
        _render_dokumentvergleich(selected_model)

    # ══════════════════════════════════════════════════════════════════════
    # TAB 2 — MUSTERLASTENHEFT
    # ══════════════════════════════════════════════════════════════════════
    with tab_muster:
        _render_musterlastenheft()
        st.divider()
        from ui.musteraufbau import render as render_musteraufbau
        render_musteraufbau(selected_model)

    # ══════════════════════════════════════════════════════════════════════
    # TAB 3 — PRAXISARCHIV
    # ══════════════════════════════════════════════════════════════════════
    with tab_praxis:
        _render_praxisarchiv()

