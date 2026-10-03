"""Gemeinsames der Kommandozeile: Befehlsgruppe, Konsole, Hilfetexte."""

import click
from rich.console import Console

from src.verzeichnisse import OUTPUT_DIR

console = Console()

OUTPUT_PATH = OUTPUT_DIR


@click.group()
def cli():
    """Lastenheft-Vergleichs-Agent mit lokalem LLM (Ollama)."""
    pass
