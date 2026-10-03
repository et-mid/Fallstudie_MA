"""Ein Kundenlastenheft prüfen und eine Agentenausgabe validieren."""

import json

import click
from pathlib import Path
from rich.markup import escape
from rich.table import Table

from src.dokumente.pdf_loader import TextExtraktionsFehler, load_document, ocr_status
from src.pruefung.kriterien import (
    MIN_SCORE,
    NUM_PREDICT,
    STANDARD_MODELL,
    evaluate_document,
    kennzahlen,
    kennzahlen_je_einstufung,
    load_kriterien,
    load_standard,
    nicht_bewertete,
    validate,
)
from src.pruefung.markierung import STUFEN
from src.bericht.excel_report import generate_excel
from src.dateien import schreibe_bytes, schreibe_json
from cli.basis import cli, console, OUTPUT_PATH


@cli.command("pruefen")
@click.argument("pdf_file", type=click.Path(exists=True))
@click.option("--model", default=STANDARD_MODELL,
              help=f"Ollama-Modell. Vorgabe {STANDARD_MODELL} — das Modell, auf das "
                   f"Prompt und Schwellen abgestimmt sind.")
@click.option("--json-out", type=click.Path(),
              help="Rohergebnis als JSON hierhin speichern (Vorgabe: output/<Datei>_bewertung.json)")
@click.option("--excel", is_flag=True, help="Prüfbericht als Excel in output/ speichern")
@click.option("--min-score", default=MIN_SCORE,
              help="Relevanzschwelle für Kandidaten-Fundstellen (0.0-1.0)")
@click.option("--lh-id", default=None, help="Kennung für die Ausgabe (Default: Dateiname)")
@click.option("--num-predict", default=NUM_PREDICT,
              help="Maximale Antwortlänge in Tokens. Für das erwartete Mini-JSON "
                   "reichen wenige Dutzend; die Grenze bremst Reasoning-Modelle, "
                   "die ihr Denken nicht beenden.")
@click.option("--quiet", is_flag=True, help="Kein Fortschritt je Kriterium")
@click.option("--ohne-praxis", is_flag=True,
              help="Praxisabgleich gegen das historische Archiv weglassen")
@click.option("--markierung", type=click.Choice(list(STUFEN)),
              default="gruendlich",
              help="Wie großzügig zusätzlich Abweichungen markiert werden "
                   "(src/pruefung/markierung.py). 'aus' = nur das Urteil des Modells.")
def pruefen_command(pdf_file: str, model: str, json_out: str, excel: bool,
                    min_score: float, lh_id: str, num_predict: int, quiet: bool,
                    ohne_praxis: bool, markierung: str):
    """Kundenlastenheft entlang der 67 Kriterien prüfen."""
    pdf_path = Path(pdf_file)
    console.print(f"[bold]Prüfe:[/bold] {pdf_path.name}")
    console.print(f"[bold]LLM-Modell:[/bold] {model}\n")

    ocr_ok, ocr_meldung = ocr_status()
    if not ocr_ok:
        console.print(f"[yellow]OCR nicht verfügbar:[/yellow] {ocr_meldung}")

    try:
        new_chunks = load_document(pdf_path, kind="neu")
    except TextExtraktionsFehler as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)
    console.print(f"  {len(new_chunks)} Abschnitte geladen.")

    kriterien = load_kriterien()
    standard  = load_standard()
    if not standard:
        console.print("[yellow]Warnung: Standard_Lastenheft_Chunks.jsonl fehlt — "
                      "ohne Vergleichsmaßstab.[/yellow]")

    def on_progress(done: int, total: int, label: str = ""):
        if not quiet:
            console.print(f"  [{done:>2}/{total}] {label}", highlight=False)

    # Der Dateiname ohne Endung ist die Kennung des Dokuments.
    ergebnis, details = evaluate_document(
        new_chunks, lh_id=lh_id or pdf_path.stem, model=model,
        min_score=min_score, num_predict=num_predict,
        kriterien=kriterien, standard=standard,
        markierung=markierung,
        progress_callback=on_progress,
    )
    console.print(f"[dim]Markierung: {markierung}[/dim]")

    # Das Ergebnis zuerst sichern, vor allem, was danach noch scheitern kann
    # (Anzeige, Praxisabgleich, Excel). Vorher stand es erst ganz am Ende auf der
    # Platte — ein beschädigtes Archiv kostete den ganzen Prüflauf. Ohne --json-out
    # landet es in output/, das nicht versioniert wird.
    ziel_json = Path(json_out) if json_out else OUTPUT_PATH / f"{pdf_path.stem}_bewertung.json"
    schreibe_json(ziel_json, ergebnis)
    console.print(f"[green]JSON gespeichert: {ziel_json}[/green]")

    offen = nicht_bewertete(details)
    if offen:
        console.print(f"\n[bold red]{len(offen)} von {len(kriterien)} Kriterien konnten "
                      f"nicht bewertet werden.[/bold red] Sie stehen als N, sind aber "
                      f"keine Aussage über das Lastenheft. Kennzahlen nicht belastbar.")
        for nr, grund in offen[:5]:
            console.print(f"  {nr}: {grund}")
        if len(offen) > 5:
            console.print(f"  … und {len(offen) - 5} weitere.")

    print_kennzahlen(ergebnis, kriterien)

    for f in validate(ergebnis, kriterien):
        console.print(f"[yellow]Strukturhinweis:[/yellow] {f}")

    befunde = None
    if not ohne_praxis:
        # Der Abgleich ist Beiwerk: Scheitert er (z. B. beschädigtes Archiv), bleibt
        # die Prüfung gültig und der Bericht entsteht ohne das Praxisblatt.
        try:
            befunde = lade_praxisbefunde(ergebnis, kriterien, standard,
                                         lh_id or pdf_path.stem)
        except Exception as e:
            console.print(f"\n[yellow]Praxisabgleich fehlgeschlagen, Bericht ohne "
                          f"Praxisblatt:[/yellow] {type(e).__name__}: {e}")

    if excel:
        target = OUTPUT_PATH / f"{pdf_path.stem}_pruefbericht.xlsx"
        schreibe_bytes(target, generate_excel(ergebnis, details, kriterien,
                                              praxis=befunde))
        console.print(f"[green]Excel gespeichert: {target}[/green]")

    if offen:
        # Nicht null: Ein Lauf, in dem das Modell nicht geantwortet hat, ist
        # kein Ergebnis — wer ihn in einem Skript weiterverarbeitet, muss das
        # am Rückgabewert erkennen können, nicht nur am Text oben.
        raise SystemExit(2)


def lade_praxisbefunde(ergebnis: dict, kriterien: list[dict],
                       standard: dict, lh_id: str):
    """Praxisabgleich rechnen und im Terminal zusammenfassen.

    Fehlt das Archiv, wird das gesagt statt still übergangen — sonst hielte
    man einen ausgefallenen Abgleich für einen unauffälligen.
    """
    from src.praxis.abgleich import LABEL, praxisabgleich, zusammenfassung
    from src.praxis.archiv import Praxisarchiv

    try:
        archiv = Praxisarchiv()
    except FileNotFoundError as e:
        console.print(f"\n[yellow]Kein Praxisabgleich:[/yellow] {e}")
        return None

    # Wird ein Dokument des Korpus selbst geprüft, darf es sich nicht
    # selbst als Erfahrungswert bestätigen.
    befunde = praxisabgleich(ergebnis, archiv=archiv, kriterien=kriterien,
                             standard=standard, ohne_dokument=lh_id)
    z = zusammenfassung(befunde)

    console.rule("[bold blue]Praxisabgleich gegen das historische Archiv")
    console.print(f"Vergleichskorpus: {z['korpus']} Lastenhefte, "
                  f"{len(archiv)} Abschnitte")
    console.print(f"üblich {z['ueblich']}  ·  selten im Korpus {z['selten']}  ·  "
                  f"Lücke {z['luecke']}  ·  unauffällig {z['unauffaellig']}")

    for b in befunde:
        if not b.auffaellig:
            continue
        farbe = "yellow" if b.einordnung == "luecke" else "cyan"
        console.print(f"\n[{farbe}]{LABEL[b.einordnung]}[/{farbe}]  "
                      f"{b.nr} {b.titel} · {b.einstufung} · Status {b.status}")
        console.print(f"  {b.n_geregelt} von {b.korpus} regeln den Punkt")
        for s in b.stellen[:2]:
            console.print(f"  [dim]{s.lh_id} S{s.seite}:[/dim] "
                          f"{s.text[:110].replace(chr(10), ' ')}", highlight=False)

    console.print("\n[dim]Häufigkeit ist keine Bewertung und sagt keine "
                  "Abweichung voraus.[/dim]")
    return befunde


def print_kennzahlen(ergebnis: dict, kriterien: list[dict]) -> None:
    """Statusübersicht und Kennzahlen im Terminal."""
    # Auch für ein Ergebnis mit fehlenden Feldern lesbar — validate() hat sie
    # oben schon gemeldet, ein KeyError hier würde die Meldung überdecken.
    if not isinstance(ergebnis.get("bewertungen"), dict):
        ergebnis = {**ergebnis, "bewertungen": {}}
    kz  = ergebnis.get("kennzahlen") or kennzahlen(ergebnis, kriterien)
    kje = kennzahlen_je_einstufung(ergebnis, kriterien)

    console.rule(f"[bold blue]Prüfbericht: {ergebnis.get('lh_id') or '(ohne Kennung)'}")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Nr", width=6)
    table.add_column("Kriterium", width=44)
    table.add_column("Einstufung", width=10)
    table.add_column("Status", width=6)
    table.add_column("Begründung")

    farbe = {"E": "green", "T": "yellow", "A": "red", "N": "dim"}
    for k in kriterien:
        b = ergebnis["bewertungen"].get(k["nr"], {})
        if not isinstance(b, dict):
            b = {"status": "?"}
        s = str(b.get("status", "N"))
        f = farbe.get(s, "white")
        table.add_row(k["nr"], k["titel"], k["einstufung"],
                      f"[{f}]{escape(s)}[/{f}]", str(b.get("begruendung", "")))
    console.print(table)

    def pct(v):
        return "—" if v is None else f"{v * 100:.1f} %".replace(".", ",")

    console.print(
        f"\nentspricht {kz['entspricht']}  ·  teilweise {kz['teilweise']}  ·  "
        f"Abweichung {kz['abweichung']}  ·  keine Vorgabe {kz['keine_vorgabe']}"
    )
    if kz.get("markiert"):
        console.print(f"zur Durchsicht markiert {kz['markiert']}  (in der Liste als A, "
                      f"oben unter dem Urteil des Modells gezählt)")
    console.print(f"Abweichungsquote   [bold]{pct(kz['abweichungsquote'])}[/bold]   "
                  "(A + 0,5 × T) / geregelt")
    console.print(f"Abdeckungsquote    [bold]{pct(kz['abdeckungsquote'])}[/bold]   "
                  f"geregelt / {len(kriterien)}")
    console.print(f"Konformitätsquote  [bold]{pct(kz['konformitaetsquote'])}[/bold]   "
                  "E / geregelt")
    console.print(f"Zusatzanforderungen {len(ergebnis.get('zusatzanforderungen') or [])} "
                  "(nicht in den Quoten enthalten)")
    console.print(f"Pflichtkriterien ohne Vorgabe: [bold]{kje['Pflicht']['N']}[/bold]")


@cli.command("pruefauftrag", hidden=True)
@click.argument("ordner", type=click.Path(exists=True, file_okay=False))
def pruefauftrag_command(ordner: str):
    """Intern: führt einen Prüfauftrag der Oberfläche als eigenen Prozess aus.

    Angelegt und gestartet wird er von ui/lastenheft.py (src/pruefung/auftrag.py);
    die Seite liest nur den Fortschritt. Rückgabewert 1, wenn kein Ergebnis entstand.
    """
    from src.pruefung import auftrag as A

    raise SystemExit(0 if A.ausfuehren(A.Auftrag(Path(ordner))) else 1)


@cli.command("validate")
@click.argument("json_file", type=click.Path(exists=True))
@click.option("--ground-truth", "gt_id", metavar="LH_ID",
              help="zusätzlich gegen ein historisches Lastenheft vergleichen (Kennung)")
def validate_command(json_file: str, gt_id: str):
    """Eine Agentenausgabe gegen die Struktur prüfen und Kennzahlen rechnen."""
    try:
        ergebnis = json.loads(Path(json_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        console.print(f"[red]{Path(json_file).name} ist nicht lesbar: {e}[/red]")
        raise SystemExit(1)
    if not isinstance(ergebnis, dict):
        console.print(f"[red]{Path(json_file).name} enthält kein Ergebnisobjekt, "
                      f"sondern {type(ergebnis).__name__}.[/red]")
        raise SystemExit(1)
    kriterien = load_kriterien()
    fehler    = validate(ergebnis, kriterien)

    if fehler:
        console.print(f"[red]{len(fehler)} Verstoß/Verstöße:[/red]")
        for f in fehler:
            console.print(f"  - {f}")
    else:
        console.print("[green]Struktur in Ordnung — alle 67 Kriterien, Belegpflicht erfüllt.[/green]")

    print_kennzahlen(ergebnis, kriterien)

    if gt_id:
        from src.auswertung.evaluation import format_bericht, vergleiche
        console.rule(f"[bold blue]Vergleich gegen Ground Truth {gt_id}")
        try:
            console.print(format_bericht(vergleiche({gt_id: ergebnis}, kriterien)))
        except KeyError as e:
            console.print(f"[red]{e.args[0]}[/red]")
            raise SystemExit(1)

    raise SystemExit(1 if fehler else 0)
