"""Befehle zum Praxisarchiv: Archiv anlegen, gegen frühere Lastenhefte vergleichen."""

import click
from pathlib import Path
from rich.table import Table

from src.dokumente.pdf_loader import TextExtraktionsFehler, load_document
from src.pruefung.kriterien import STANDARD_MODELL
from cli.basis import cli, console


@cli.command("praxis-index")
@click.argument("ordner", type=click.Path(exists=True))
@click.option("--alle", is_flag=True,
              help="auch Dokumente aufnehmen, die nicht zum Korpus des "
                   "Musterlastenhefts gehören")
def praxis_index_command(ordner: str, alle: bool):
    """Praxisarchiv aus den historischen Lastenheften anlegen.

    ORDNER enthält die Dateien LHD-*.pdf. Das Musterlastenheft wird
    ausgeschlossen — der Maßstab gehört nicht ins Erfahrungsarchiv.
    """
    from src.praxis.abgleich import korpus_ids
    from src.praxis.archiv import baue_archiv

    console.print(f"[bold]Lege Praxisarchiv an aus:[/bold] {ordner}")

    def on_progress(i: int, n: int, name: str):
        console.print(f"  [{i:>2}/{n}] {name}", highlight=False)

    try:
        b = baue_archiv(Path(ordner), erlaubte_ids=None if alle else korpus_ids(),
                        progress_callback=on_progress)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)

    console.print(f"[green]{len(b.dokumente)} Dokumente, {b.abschnitte} Abschnitte "
                  f"in {b.dauer_s:.0f}s.[/green]")
    for u in b.uebersprungen:
        console.print(f"[yellow]übersprungen:[/yellow] {u}")


@cli.command("vergleichen")
@click.argument("pdf_file", type=click.Path(exists=True))
@click.option("--gegen", default=None, metavar="LH_ID",
              help="Vergleichsdokument fest wählen statt das ähnlichste zu nehmen")
@click.option("--model", default=None, help=f"Ollama-Modell (Vorgabe {STANDARD_MODELL})")
@click.option("--nur-rangliste", is_flag=True,
              help="nur die ähnlichsten Lastenhefte anzeigen, ohne Abschnittsvergleich")
def vergleichen_command(pdf_file: str, gegen: str, model: str, nur_rangliste: bool):
    """Ein Lastenheft gegen die historischen Lastenhefte vergleichen.

    Ohne Bezug zum Musterlastenheft: Die Rangliste entsteht aus dem
    Textvergleich der Dokumente, der Abschnittsvergleich aus dem Sprachmodell.
    """
    from src.praxis import dokumentvergleich as DV
    from src.praxis.archiv import Praxisarchiv

    pfad = Path(pdf_file)
    try:
        archiv = Praxisarchiv()
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)

    try:
        chunks = load_document(pfad, kind="neu")
    except TextExtraktionsFehler as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)

    brauchbar = [c for c in chunks if not DV.ist_schrott(c.text)]
    console.print(f"[bold]{pfad.name}[/bold]: {len(brauchbar)} verwertbare von "
                  f"{len(chunks)} Abschnitten")

    neu_norm = DV._neue_embeddings(brauchbar)
    rang = DV.rangliste(brauchbar, archiv, neu_norm=neu_norm, ohne=pfad.stem)

    console.rule("[bold blue]Ähnlichste frühere Lastenhefte")
    t = Table(show_header=True, header_style="bold")
    t.add_column("Lastenheft", width=12)
    t.add_column("Rangwert", width=12, justify="right")
    t.add_column("vergleichbare Abschnitte", width=24, justify="right")
    t.add_column("Umfang", width=8, justify="right")
    for d in rang[:10]:
        t.add_row(d.lh_id, f"{d.wert:.3f}", str(d.vergleichbar), str(d.abschnitte))
    console.print(t)
    console.print("[dim]Die Reihenfolge ist ein Vorschlag. Der Rangwert ordnet nur, "
                  "er ist keine Ähnlichkeit in Prozent.[/dim]")

    if nur_rangliste or not rang:
        return

    ziel = gegen or rang[0].lh_id
    if ziel not in [d.lh_id for d in rang]:
        console.print(f"[red]{ziel} ist nicht im Archiv.[/red] Verfügbar: "
                      + ", ".join(d.lh_id for d in rang))
        raise SystemExit(1)

    paare, vergleichbar = DV.abschnittspaare(brauchbar, archiv, ziel,
                                             neu_norm=neu_norm)
    console.rule(f"[bold blue]Abschnittsvergleich gegen {ziel}")
    if not paare:
        console.print(f"[yellow]Keine vergleichbaren Abschnitte.[/yellow] Beide "
                      f"Dokumente sind unabhängig voneinander geschrieben; "
                      f"unterhalb der Schwelle von {DV.MIN_PAAR_SCORE:.2f} wären "
                      f"die Paare nicht besser als zufällig gezogen.")
        return

    def on_progress(i: int, n: int, label: str):
        console.print(f"  [{i:>2}/{n}] {label}", highlight=False)

    DV.vergleiche_abschnitte(paare, ziel, model=model or STANDARD_MODELL,
                             progress_callback=on_progress)
    erg = DV.auswerten(paare, vergleichbar, ziel, len(brauchbar))
    bewertet = len(erg.paare) - erg.nicht_bewertet

    if erg.uebereinstimmung is None:
        console.print("\n[bold]Ähnlichkeit: keine Aussage[/bold] — kein Paar "
                      "ließ sich bewerten.")
    else:
        console.print(f"\n[bold]Ähnlichkeit {erg.uebereinstimmung:.0%}[/bold] — "
                      f"gemittelt über {bewertet} verglichene Stellen.")
    console.print(f"Vergleichbare Abschnitte: {erg.vergleichbar} von "
                  f"{erg.abschnitte_neu}")
    console.print(f"[dim]Der Wert sagt etwas über diese Stellen, nicht über die "
                  f"Dokumente als Ganzes.[/dim]\n")
    for b, n in DV.zusammenfassung(erg).items():
        if n:
            console.print(f"  {b}: {n}")

    for p in sorted(erg.paare, key=lambda x: (x.wert if x.wert is not None else -1)):
        wert = f"{p.wert:>3} %" if p.wert is not None else "  — "
        console.print(f"\n[bold]{wert}[/bold] Seite {p.seite_neu} gegen {ziel} "
                      f"Seite {p.seite_alt}")
        console.print(f"  {p.fehler or p.unterschied}", highlight=False)
