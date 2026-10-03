"""Kommandozeile. Einstieg: `python main.py <befehl>`.

Die Befehle liegen nach Aufgabe getrennt in den Modulen dieses Pakets; der
Import registriert sie an der gemeinsamen Gruppe `cli`.
"""

from cli.basis import cli
from cli import messung, muster, praxis, pruefung  # noqa: F401  (registriert die Befehle)

__all__ = ["cli"]
