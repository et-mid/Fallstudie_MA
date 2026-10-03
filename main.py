"""Lastenheft-Prüfagent — Einstieg für die Kommandozeile.

Die Befehle stehen in cli/: pruefung.py (pruefen, validate), messung.py
(evaluieren, modelle, modellvergleich, list-models), muster.py
(standardhaltung, muster-vorschlag, muster-aufbauen), praxis.py (praxis-index,
vergleichen).
"""

from cli import cli

if __name__ == "__main__":
    cli()
