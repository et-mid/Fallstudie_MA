"""Oberfläche für den Musteraufbau: Lastenhefte hochladen, Gliederung prüfen, Entwurf holen.

Der Aufbau läuft als eigener Prozess über `main.py muster-vorschlag` und
`main.py muster-aufbauen`, nicht im Streamlit-Skript. Er dauert je nach Umfang
eine Stunde und länger; ein Streamlit-Lauf, der so lange rechnet, bricht beim
ersten Neuladen der Seite ab und hätte nichts gesichert. Der Prozess schreibt
seinen Fortschritt in den Arbeitsordner, die Oberfläche liest ihn nur.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st

from src.muster import musteraufbau as MA

BASE_DIR = Path(__file__).parent.parent

SPALTEN = {"aktiv": "Übernehmen", "kapitel": "Kapitel", "titel": "Kriterium",
           "belegt": "Belegt in", "beispiele": "Überschriften in den Lastenheften"}


def _starten(stand: MA.Arbeitsstand, phase: str, argumente: list[str]) -> None:
    stand.ordner.mkdir(parents=True, exist_ok=True)
    # Ein altes Lebenszeichen darf den neuen Lauf nicht schon als lebend ausweisen.
    try:
        stand.puls.unlink()
    except OSError:
        pass
    # Sofort als laufend markieren, damit ein zweiter Klick nicht doppelt startet.
    stand.melden(phase, 0, 1, "Wird gestartet …")
    # Das Kind bekommt eine eigene Kopie des Handles; die des Elternprozesses
    # darf gleich wieder zu — sonst bleibt je Start eine Datei offen.
    with stand.protokoll.open("a", encoding="utf-8") as protokoll:
        subprocess.Popen(
            [sys.executable, str(BASE_DIR / "main.py"), *argumente],
            cwd=str(BASE_DIR), stdout=protokoll, stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt")


def _fortschritt(stand: MA.Arbeitsstand) -> None:
    """Fortschrittsanzeige. Wird in render() als Fragment eingehängt, das sich
    nur dann alle vier Sekunden neu zeichnet, wenn ein Aufbau läuft — sonst
    hielte es die Seite dauerhaft in Bewegung, in jedem Reiter, weil Streamlit
    alle Tabs rendert."""
    f = stand.lesen(stand.fortschritt)
    if not f:
        return
    phase = "Gliederung vorschlagen" if f.get("phase") == "vorschlag" else "Inhalte erzeugen"
    if f.get("fehler") == MA.ABGEBROCHEN:
        st.info(f"**{phase}** wurde abgebrochen. Bereits Gesichertes bleibt erhalten; "
                f"ein neuer Start setzt darauf auf.")
    elif f.get("fehler"):
        st.error(f"**{phase} abgebrochen:** {f['fehler']}")
        st.caption(f"Protokoll: {stand.protokoll}")
    elif f.get("fertig"):
        st.success(f"**{phase}:** {f.get('text', '')}")
    elif MA.laeuft(stand):
        gesamt = max(int(f.get("gesamt") or 1), 1)
        st.progress(min(int(f.get("schritt") or 0) / gesamt, 1.0),
                    text=f"**{phase}** · {f.get('text', '')}")
        links, rechts = st.columns([2, 1])
        links.caption("Läuft im Hintergrund weiter.",
                      help="Auch wenn diese Seite geschlossen wird. Nach einem Abbruch "
                           "setzt ein neuer Start auf dem Gesicherten auf.")
        if rechts.button("Abbrechen", key="ma_abbrechen", use_container_width=True):
            MA.abbrechen(stand)
            st.rerun(scope="app")
    else:
        st.warning(f"**{phase}** gibt seit über {MA.PULS_GRENZE} s kein Lebenszeichen "
                   f"mehr — der Prozess ist beendet. Protokoll: {stand.protokoll}")
    # Ist ein Lauf gerade fertig geworden, die ganze Seite neu aufbauen, damit
    # Gliederung oder Entwurf erscheinen.
    if f.get("fertig") and not st.session_state.get(f"ma_gesehen_{f.get('aktualisiert')}"):
        st.session_state[f"ma_gesehen_{f.get('aktualisiert')}"] = True
        st.rerun()


def _zeilen_als_tabelle(zeilen: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "id": z.get("id", ""),
        "aktiv": bool(z.get("aktiv", True)),
        "kapitel": z.get("kapitel", ""),
        "titel": z.get("titel", ""),
        "belegt": len(z.get("belegt_in") or []),
        "beispiele": " · ".join(z.get("beispiele") or []),
    } for z in zeilen])


def _tabelle_als_zeilen(tabelle: pd.DataFrame, alt: list[dict]) -> list[dict]:
    """Übernimmt die Bearbeitung; Belege und Beispiele bleiben am Thema hängen."""
    je_id = {z.get("id"): z for z in alt}
    zeilen = []
    for _, r in tabelle.iterrows():
        titel = str(r.get("titel") or "").strip()
        if not titel:
            continue
        kennung = str(r.get("id") or "").strip() or f"N{uuid.uuid4().hex[:6]}"
        vorher = je_id.get(kennung, {})
        zeilen.append({
            "id": kennung,
            "aktiv": bool(r.get("aktiv")) if pd.notna(r.get("aktiv")) else True,
            "kapitel": str(r.get("kapitel") or "").strip() or "Allgemeines",
            "titel": titel,
            "belegt_in": vorher.get("belegt_in", []),
            "beispiele": vorher.get("beispiele", []),
        })
    return zeilen


def render(selected_model: str) -> None:
    st.markdown("**Neues Musterlastenheft aus Lastenheften erstellen**",
                help="Für ein Anwendungsfeld ohne Standard: Aus mehreren "
                     "Kundenlastenheften entsteht ein Entwurf im Format oben, der in "
                     "Word überarbeitet und dann hinterlegt wird. Alles bleibt lokal.")

    stand = MA.Arbeitsstand()
    gliederung = stand.lesen(stand.gliederung) or {}
    laufend = MA.laeuft(stand)

    modell = selected_model or MA.MODELL

    # ── 1 · Lastenhefte und Anwendungsfeld ──────────────────────────────────
    with st.container(border=True):
        st.markdown("**1 · Lastenhefte und Anwendungsfeld**")
        gegenstand = st.text_input(
            "Anwendungsfeld, in der Mehrzahl", value=gliederung.get("gegenstand", ""),
            placeholder="z. B. Schaltschränke", key="ma_gegenstand",
            help="Steht im Musterlastenheft als Gegenstand und in jedem Prompt "
                 "(„Kundenlastenheft für …“).")
        hochgeladen = st.file_uploader("Kundenlastenhefte (PDF oder Word)",
                                       type=[s.lstrip(".") for s in MA.SUFFIXE],
                                       accept_multiple_files=True, key="ma_upload")
        if hochgeladen:
            # Jede Datei nur einmal schreiben: Der Uploader hält sie über jeden
            # Neuaufbau fest, und ein entferntes Lastenheft käme sonst gleich zurück.
            geschrieben = st.session_state.setdefault("ma_geschrieben", set())
            stand.dokumente.mkdir(parents=True, exist_ok=True)
            for f in hochgeladen:
                if f.file_id not in geschrieben:
                    (stand.dokumente / Path(f.name).name).write_bytes(f.getvalue())
                    geschrieben.add(f.file_id)

        dateien = stand.dateien()
        if dateien:
            with st.expander(f"**{len(dateien)} Lastenhefte** hochgeladen"):
                for p in dateien:
                    name, knopf = st.columns([5, 1])
                    name.caption(p.name)
                    if knopf.button("✕", key=f"ma_entfernen_{p.name}",
                                    disabled=laufend, use_container_width=True,
                                    help=f"{p.name} entfernen — löscht die Datei aus "
                                         f"dem Arbeitsordner. Während ein Aufbau "
                                         f"läuft, nicht möglich."):
                        MA.entfernen(stand, p.name)
                        st.rerun()
        if len(dateien) == 1:
            st.caption("Ein Lastenheft genügt.",
                       help="Seine Gliederung wird ins Musterformat übernommen. Jeder "
                            "Abschnitt ist dann als Pflicht eingestuft — über die "
                            "Häufigkeit sagt die Einstufung erst mit weiteren "
                            "Lastenheften etwas.")

        ueberschreiben = True
        if gliederung.get("zeilen"):
            ueberschreiben = st.checkbox(
                "Vorhandene Gliederung und bereits erzeugte Inhalte verwerfen",
                key="ma_neu", value=False)
        if st.button("Gliederung vorschlagen", key="ma_vorschlag",
                     disabled=laufend or not gegenstand.strip() or not dateien
                     or not ueberschreiben,
                     help="Liest die Kapitelüberschriften aller Lastenhefte, übernimmt jedes "
                          "Thema und fasst gleiche Themen verschiedener Lastenhefte "
                          "zusammen. Scans werden beim ersten Mal per "
                          "Texterkennung gelesen — das dauert am längsten."):
            _starten(stand, "vorschlag", ["muster-vorschlag", "--gegenstand",
                                          gegenstand.strip(), "--model", modell])
            st.rerun()

    st.fragment(run_every=4 if laufend else None)(_fortschritt)(stand)

    # ── 2 · Gliederung prüfen ───────────────────────────────────────────────
    zeilen = gliederung.get("zeilen") or []
    if not zeilen:
        return
    with st.container(border=True):
        st.markdown("**2 · Gliederung prüfen**",
                    help="Die Gliederung trägt später jede Prüfung. Haken entfernen "
                         "streicht ein Thema, Titel und Kapitel sind änderbar, unten "
                         "lassen sich Zeilen ergänzen. Zeilenreihenfolge = Reihenfolge "
                         "im Musterlastenheft.")
        st.caption(f"{len(zeilen)} Themen aus {len(gliederung.get('dokumente') or [])} "
                   f"Lastenheften — enthält überzählige und zusammengewürfelte Themen.")
        bearbeitet = st.data_editor(
            _zeilen_als_tabelle(zeilen), key="ma_editor", num_rows="dynamic",
            use_container_width=True, hide_index=True,
            column_order=["aktiv", "kapitel", "titel", "belegt", "beispiele"],
            column_config={
                "aktiv": st.column_config.CheckboxColumn(SPALTEN["aktiv"], default=True, width="small"),
                "kapitel": st.column_config.TextColumn(SPALTEN["kapitel"], width="medium"),
                "titel": st.column_config.TextColumn(SPALTEN["titel"], width="large", required=True),
                "belegt": st.column_config.NumberColumn(
                    SPALTEN["belegt"], disabled=True, width="small",
                    help="Lastenhefte mit eigener Überschrift zum Thema — daraus wird "
                         "die Einstufung Pflicht / Regel / Optional. Beim Befüllen "
                         "kommen Lastenhefte mit sehr ähnlichen Stellen hinzu."),
                "beispiele": st.column_config.TextColumn(SPALTEN["beispiele"], disabled=True),
            })
        neu = _tabelle_als_zeilen(bearbeitet, zeilen)
        aktiv = MA.nummerieren([dict(z) for z in neu])
        st.caption(f"**{len(aktiv)} Kriterien** in **{len({z['kapitel'] for z in aktiv})} "
                   f"Kapiteln**")

        links, rechts = st.columns(2)
        if links.button("Gliederung speichern", key="ma_speichern", disabled=laufend,
                        use_container_width=True):
            stand.schreiben(stand.gliederung, {**gliederung, "zeilen": neu, "geprueft": True})
            st.success("Gespeichert.")
        fertig = stand.lesen(stand.inhalte, {}) or {}
        bisher = sum(1 for z in aktiv if (fertig.get(z["id"]) or {}).get("titel") == z["titel"])
        if rechts.button("Inhalte erzeugen", type="primary", key="ma_inhalte",
                         disabled=laufend or not aktiv, use_container_width=True,
                         help=f"Ein Modellaufruf je Kriterium, rund eine Minute — hier "
                              f"etwa {len(aktiv)} Minuten."
                              + (f" {bisher} bereits erzeugt, werden übernommen." if bisher else "")):
            stand.schreiben(stand.gliederung, {**gliederung, "zeilen": neu, "geprueft": True})
            _starten(stand, "inhalte", ["muster-aufbauen", "--model", modell])
            st.rerun()

    # ── 3 · Entwurf ─────────────────────────────────────────────────────────
    entwurf = stand.entwurf(gliederung.get("gegenstand", ""))
    if not entwurf.exists() or laufend:
        return
    with st.container(border=True):
        st.markdown("**3 · Entwurf**")
        inhalte = stand.lesen(stand.inhalte, {}) or {}
        ok = sum(1 for i in inhalte.values() if i.get("status") == "ok" and i.get("standardanforderungen"))
        ohne = [f"{i.get('titel')}: {i.get('fehler') or 'keine Anforderungen'}"
                for i in inhalte.values() if not (i.get("status") == "ok" and i.get("standardanforderungen"))]
        st.markdown(f"**{ok} Kriterien befüllt**" + (f", {len(ohne)} ohne Inhalt" if ohne else ""),
                    help="Vor dem Hinterlegen in Word durchsehen. Einstufung Pflicht / "
                         "Regel / Optional ist eine grobe Schätzung. Standardanforderungen sind Modelltext. "
                         "Ausprägungen sind gegen ihre Quelle geprüft, können aber "
                         "Hersteller und Werknormen der Kunden nennen.")
        if ohne:
            with st.expander("Ohne Inhalt — in Word zu ergänzen", expanded=False):
                for o in ohne:
                    st.markdown(f"- {o}")
        links, rechts = st.columns(2)
        links.download_button("Entwurf herunterladen (.docx)", data=entwurf.read_bytes(),
                              file_name=entwurf.name, key="ma_download",
                              use_container_width=True,
                              mime="application/vnd.openxmlformats-officedocument."
                                   "wordprocessingml.document")
        if rechts.button("In die Vorschau laden", key="ma_vorschau",
                         use_container_width=True,
                         help="Die Vorschau steht oben in diesem Reiter. Hinterlegt wird "
                              "erst auf Bestätigung."):
            st.session_state["muster_entwurf"] = str(entwurf)
            st.rerun()
