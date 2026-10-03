"""App-Router — steuert welche Seite angezeigt wird."""

import streamlit as st
import ollama as ollama_client

st.set_page_config(page_title="Lastenheft-Prüfagent", page_icon="📐",
                   layout="wide")

# Das Aussehen liegt vollständig in ui/design.py — Token, Bauteile und die
# Übersetzung auf Streamlits Bedienelemente. Hier steht nur der Aufruf, damit
# man an einer Stelle nachschlägt statt an zweien.
from ui.design import einspielen, kopf

einspielen()


# ── Ollama-Modelle (gecacht: max. 1 HTTP-Request pro 10 s statt pro Rerun) ──
@st.cache_data(ttl=10, show_spinner=False)
def list_ollama_models() -> list[str]:
    try:
        _resp = ollama_client.list()
        _raw = _resp["models"] if isinstance(_resp, dict) else _resp.models
        models: list[str] = []
        for _m in _raw:
            _name = getattr(_m, "model", None) or getattr(_m, "name", None)
            if _name is None and isinstance(_m, dict):
                _name = _m.get("model") or _m.get("name")
            if _name:
                models.append(_name)
        return models
    except Exception:
        return []


from src.pruefung.kriterien import (
    MIN_SCORE, STANDARD_MODELL, agent_prompt, gliederung_als_text,
    load_kriterien,
)
from src.muster.anwendungsfeld import aktuell as anwendungsfeld_aktuell
from src.umgebung import bereit, pruefe_alles
from ui.verbindung import render as render_verbindung

# Modellvorgabe und Schwelle stehen in src/pruefung/kriterien.py.

# ── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Status")

    punkte = pruefe_alles()
    for p in punkte:
        if p.ok:
            st.markdown(f"✅  **{p.name}** — {p.meldung}")
        else:
            symbol = "❌" if p.blockend else "⚠️"
            st.markdown(f"{symbol}  **{p.name}** — {p.meldung}")

    st.divider()

    available_models = list_ollama_models()
    vorgabe = (STANDARD_MODELL if STANDARD_MODELL in available_models
               else (available_models[0] if available_models else STANDARD_MODELL))

    # Die Modellwahl liegt in ui/verbindung.py — nur lokale Modelle, weil das
    # Briefing verlangt, dass Kundendokumente den Rechner nicht verlassen.
    selected_model = render_verbindung(available_models, vorgabe)

    # Ein ersatzweise gewähltes lokales Modell darf nicht stillschweigend
    # durchgehen: Die berichtete Trefferquote gilt dann nicht mehr.
    if (available_models and selected_model in available_models
            and selected_model != STANDARD_MODELL):
        if STANDARD_MODELL not in available_models:
            st.warning(
                f"**{STANDARD_MODELL} fehlt** — Prüfung mit `{selected_model}`; die "
                f"Vorgaben sind auf das Standardmodell abgestimmt.\n\n"
                f"`ollama pull {STANDARD_MODELL}`")
        else:
            st.info(
                f"Anderes Modell gewählt: `{selected_model}`. Die Vorgaben sind auf "
                f"{STANDARD_MODELL} abgestimmt; die berichteten Kennzahlen gelten "
                f"für dieses Modell nicht.")

    # Ähnlichkeitsschwelle und Prompt sind bewusst keine Bedienelemente: Beide sind
    # auf das Standardmodell abgestimmt, und Verstellen verschlechtert das Ergebnis,
    # ohne dass es sichtbar wird. Erreichbar über die CLI (--min-score).
    min_similarity = MIN_SCORE
    custom_prompt = None

    st.divider()
    with st.expander("⚙️  Erweiterte Einstellungen", expanded=False):
        st.caption(f"Schwelle {MIN_SCORE:.2f} und Prompt fest eingestellt",
                   help="Beide Werte sind auf das Standardmodell abgestimmt. Für "
                        "Untersuchungen über die Kommandozeile (--min-score).")

        st.markdown("**Agenten-Auftrag**", help="Nur zum Nachlesen.")
        st.text_area(
            "Agenten-Auftrag",
            value=agent_prompt().format(
                gliederung=gliederung_als_text(load_kriterien())),
            height=240, disabled=True, label_visibility="collapsed",
            key="agent_prompt_view")

# ── Hauptbereich ────────────────────────────────────────────────────────────
kopf(
    "Lastenheft-Prüfung",
    "Kundenlastenheft gegen Musterlastenheft prüfen. "
    "<strong>Prüfhilfe, kein Ersatz für die fachliche Durchsicht.</strong>",
    # Das Anwendungsfeld des hinterlegten Musterlastenhefts, nicht fest Druckguss.
    kicker=anwendungsfeld_aktuell().gegenstand_mehrzahl,
)

# Fehlende Voraussetzungen nach vorn, mit konkreter Handlungsanweisung.
for p in punkte:
    if not p.ok:
        (st.error if p.blockend else st.warning)(f"**{p.meldung}**\n\n{p.hinweis}")

st.divider()
from ui.lastenheft import render
render(selected_model=selected_model,
       min_similarity=min_similarity,
       custom_prompt=custom_prompt,
       startklar=bereit(punkte))
