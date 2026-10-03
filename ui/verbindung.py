"""Modellwahl in der Oberfläche — nur Modelle auf diesem Rechner.

Das Briefing verlangt, dass Kundendokumente den Rechner nicht verlassen. Es gibt
deshalb nur lokale Modelle über Ollama.
"""

from __future__ import annotations

import streamlit as st


def render(lokale_modelle: list[str], vorgabe: str) -> str:
    """Zeichnet die Modellwahl und gibt den gewählten Ollama-Namen zurück."""
    st.markdown("### Sprachmodell",
                help="Läuft auf diesem Rechner. Kein Dokument verlässt ihn.")
    if lokale_modelle:
        idx = lokale_modelle.index(vorgabe) if vorgabe in lokale_modelle else 0
        return st.selectbox("Modell", lokale_modelle, index=idx, key="lokales_modell")
    st.warning("Ollama meldet kein Modell. Läuft der Dienst?")
    return st.text_input("Modell", value=vorgabe, key="lokales_modell_frei")
