"""Messläufe gegen die Ground Truth, Modellprüfung und Modellvergleich."""

import json
import time

import click
from pathlib import Path
from rich.table import Table

from src.dokumente.pdf_loader import TextExtraktionsFehler, load_document
from src.pruefung.kriterien import (
    MIN_SCORE,
    NUM_CTX,
    NUM_PREDICT,
    STANDARD_MODELL,
    STATUS_WERTE,
    evaluate_document,
    kennzahlen,
    load_kriterien,
    load_standard,
    nicht_bewertete,
)
from src.pruefung.markierung import STUFEN
from cli.basis import cli, console
from src.dateien import schreibe_json


@cli.command("evaluieren")
@click.argument("pdf_folder", type=click.Path(exists=True))
@click.option("--model", default=STANDARD_MODELL, help="Ollama-Modell")
@click.option("--min-score", default=MIN_SCORE, help="Relevanzschwelle (0.0-1.0)")
@click.option("--limit", default=0, help="Nur die ersten N Dokumente prüfen (0 = alle)")
@click.option("--json-out", type=click.Path(), help="Alle Agentenausgaben als JSON speichern")
@click.option("--ohne-querverweise", is_flag=True,
              help="Querverweise aus fremden Standardabschnitten weglassen (für Vergleichsläufe)")
@click.option("--mit-abweichungspass", is_flag=True,
              help="Zusätzlichen Abweichungs-Durchgang fahren (erprobt und verworfen, "
                   "kostet deutlich Laufzeit)")
@click.option("--neu", is_flag=True,
              help="vorhandene Zwischenstände in --json-out verwerfen und alles "
                   "neu rechnen")
@click.option("--teil", type=click.Choice(["alle", "training", "stichprobe",
                                           "held-out"]),
              default="alle",
              help="Korpusteil: 'training' (hier darf justiert werden), 'stichprobe' "
                   "(feste Auswahl für schnelle Vergleiche) oder 'held-out' "
                   "(nur zur Endmessung)")
@click.option("--referenzbeispiele", is_flag=True,
              help="Je Kriterium bewertete Fälle aus anderen Lastenheften in den Prompt "
                   "(erprobt, ohne Effekt).")
@click.option("--entscheider", is_flag=True,
              help="Gelernten Entscheider anwenden (N auf E/T heben). Vorgabe aus: evaluieren "
                   "misst das Modellurteil. Achtung: Auf den Dokumenten, an denen der "
                   "Entscheider trainiert wurde, ist das Ergebnis geschönt.")
@click.option("--neutrales-beispiel", is_flag=True,
              help="Formatbeispiel im Prompt ohne konkreten Status (erprobt und verworfen).")
@click.option("--n-nachpruefung", is_flag=True,
              help="Jedes vom Modell vergebene N mit einem Zitat-Durchgang nachprüfen "
                   "(erprobt und verworfen).")
@click.option("--wahrscheinlichkeiten", is_flag=True,
              help="Je Kriterium die Wahrscheinlichkeiten von E/T/A/N mitschreiben "
                   "(Token-Wahrscheinlichkeiten, kein zusätzlicher Aufruf, nur lokal).")
@click.option("--markierung", type=click.Choice(list(STUFEN)),
              default="aus",
              help="Vorgabe 'aus': das reine Modellurteil, vergleichbar mit allen "
                   "früheren Messungen. Jede Stufe lässt sich aus einem solchen Lauf "
                   "nachträglich berechnen (src/markierung.markieren).")
@click.option("--ground-truth", "gt_pfad", type=click.Path(exists=True, dir_okay=False),
              default=None,
              help="Andere Referenzbewertungen (Format wie data/Ground_Truth_Lastenheft_"
                   "Abgleich_v1.5.json), z. B. für ein anderes Musterlastenheft. Sie müssen "
                   "zum aktiven Musterlastenheft passen.")
def evaluieren_command(pdf_folder: str, model: str, min_score: float, limit: int,
                       json_out: str, ohne_querverweise: bool,
                       mit_abweichungspass: bool, neu: bool, teil: str,
                       referenzbeispiele: bool, entscheider: bool,
                       neutrales_beispiel: bool, n_nachpruefung: bool,
                       wahrscheinlichkeiten: bool, markierung: str,
                       gt_pfad: str | None):
    """Den Agenten über die 18 historischen Lastenhefte laufen lassen und gegen die
    Ground Truth auswerten.

    PDF_FOLDER enthält die Dateien LHD-*.pdf (bzw. die Kennungen der mit
    --ground-truth gewählten Referenz). Der Dateiname ohne Endung ist die lh_id.
    """
    from src.auswertung.evaluation import (format_bericht, korpus, load_ground_truth,
                                vergleiche)

    kriterien = load_kriterien()
    standard  = load_standard()
    gt        = load_ground_truth(Path(gt_pfad) if gt_pfad else None)
    if gt_pfad:
        # Training, Stichprobe und Held-out sind Kennungen der Druckguss-Referenz.
        if teil != "alle":
            console.print("[red]--teil gilt nur für die Druckguss-Referenz; mit "
                          "--ground-truth wird über alle ihre Dokumente gemessen.[/red]")
            raise SystemExit(1)
        soll = {k["nr"] for k in gt.get("kriterien", [])}
        ist = {k["nr"] for k in kriterien}
        if soll != ist:
            console.print(f"[red]{Path(gt_pfad).name} passt nicht zum aktiven "
                          f"Musterlastenheft ({len(soll)} gegen {len(ist)} Kriterien, "
                          f"{len(soll ^ ist)} Nummern verschieden). Erst das passende "
                          f"Musterlastenheft aktivieren.[/red]")
            raise SystemExit(1)

    erlaubt = set(korpus(gt, teil.replace("-", "_")))
    dateien = sorted(p for p in Path(pdf_folder).iterdir()
                     if p.is_file() and p.stem in erlaubt)
    if not dateien:
        console.print(f"[red]Keine Dokumente aus der Ground Truth in {pdf_folder} gefunden.[/red]")
        console.print("Erwartete Dateinamen: " + ", ".join(sorted(erlaubt)[:5]) + " …")
        raise SystemExit(1)
    if limit:
        dateien = dateien[:limit]

    console.print(f"[bold]{len(dateien)} Dokument(e), Modell {model}[/bold]")
    if teil == "held-out":
        console.print("[bold yellow]Held-out-Lauf. Diese Dokumente tragen die "
                      "einzige Zahl, die für unbekannte Lastenhefte spricht — "
                      "nach dieser Messung darf nichts mehr justiert werden.[/bold yellow]")
    console.print()

    ergebnisse, offen = lauf_ueber_dokumente(
        dateien, model, kriterien, standard, min_score=min_score,
        json_out=Path(json_out) if json_out else None, neu=neu,
        mit_querverweisen=not ohne_querverweise,
        mit_abweichungspass=mit_abweichungspass,
        markierung=markierung,
        mit_entscheider=entscheider,
        referenzbeispiele=referenzbeispiele,
        mit_wahrscheinlichkeiten=wahrscheinlichkeiten,
        mit_n_nachpruefung=n_nachpruefung,
        neutrales_beispiel=neutrales_beispiel)

    if json_out:
        console.print(f"[green]Ausgaben gespeichert: {json_out}[/green]")

    summe = sum(offen.values())
    if summe:
        console.print(f"[bold red]{summe} Kriterien konnten nicht bewertet "
                      f"werden.[/bold red] Sie stehen als N und sind hier keine "
                      f"Aussage über das Lastenheft — die Kennzahlen sind "
                      f"entsprechend nicht belastbar.")

    console.rule("[bold blue]Evaluation gegen Ground Truth")
    console.print(format_bericht(vergleiche(ergebnisse, kriterien, gt)))


def _nebendatei(json_out: Path) -> Path:
    """Ablage für Angaben, die nicht ins Ausgabeformat gehören."""
    return json_out.with_suffix(json_out.suffix + ".lauf")


def _erwartete_bedingungen(model: str, min_score: float, standard: dict,
                           opts: dict) -> dict:
    """Die Laufbedingungen, die ein übernommenes Ergebnis teilen muss."""
    from src.pruefung.standardhaltung import fingerabdruck
    return {
        "modell": model,
        "min_score": round(float(min_score), 4),
        "standard_fingerabdruck": fingerabdruck(standard),
        "entscheider": bool(opts.get("mit_entscheider", True)),
    }


def _abweichende_bedingungen(ergebnis: dict, erwartet: dict) -> list[str]:
    """Felder, in denen ein gespeichertes Ergebnis vom laufenden Aufruf abweicht.
    Was im Ergebnis fehlt, gilt als unbekannt und nicht als Abweichung."""
    s = ergebnis.get("steckbrief") or {}
    vorhanden = {k: s[k] for k in ("modell", "min_score", "standard_fingerabdruck")
                 if k in s}
    if "entscheider" in ergebnis:
        vorhanden["entscheider"] = ergebnis["entscheider"] != "aus"
    return sorted(k for k, v in vorhanden.items() if v != erwartet[k])


def lauf_ueber_dokumente(dateien, model: str, kriterien, standard,
                         min_score: float = MIN_SCORE, json_out: Path | None = None,
                         neu: bool = False, **opts
                         ) -> tuple[dict[str, dict], dict[str, int]]:
    """Prüft eine Liste von Dokumenten und sichert nach jedem Zwischenstand.

    Ein Lauf über 18 Lastenhefte dauert rund eine Stunde. Bricht er ab — ein
    Absturz von Ollama genügt —, war ohne Zwischenspeicherung alles verloren.
    Liegt die Zieldatei vor, werden die darin enthaltenen Dokumente
    übersprungen; `neu` erzwingt den vollständigen Durchlauf.

    Zweiter Rückgabewert: Zahl der nicht bewerteten Kriterien je Dokument.
    Sie steht NICHT in der Agentenausgabe, denn dort ist ein gescheiterter
    Aufruf von einem echten „keine Vorgabe" nicht zu unterscheiden — beide
    tragen Status N mit leeren Feldern. Deshalb eine Nebendatei; sie überlebt
    damit auch eine Wiederaufnahme.
    """
    ergebnisse: dict[str, dict] = {}
    offen_je_dok: dict[str, int] = {}

    if json_out and json_out.exists() and not neu:
        try:
            ergebnisse = json.loads(json_out.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            # Nicht als leer behandeln: Sonst rechnet der Lauf von vorn und
            # überschreibt, was an der Datei vielleicht noch zu retten ist.
            console.print(f"[bold red]Abbruch:[/bold red] {json_out.name} ist nicht "
                          f"lesbar ({e}). Datei prüfen oder beiseitelegen, oder mit "
                          f"--neu bewusst neu rechnen.")
            raise SystemExit(1)
        if ergebnisse:
            console.print(f"[dim]{len(ergebnisse)} Dokument(e) aus "
                          f"{json_out.name} übernommen — mit --neu neu "
                          f"rechnen.[/dim]")

        # Entstand der Zwischenstand unter einer anderen Markierungsstufe? Die
        # fertigen Dokumente würden übersprungen, und herauskäme eine Kennzahl
        # über zwei Einstellungen, die wie eine Messung aussieht. Abbruch statt
        # Warnung: Wer eine Warnung überliest, hat eine Zahl in der Hand, der
        # man nichts mehr ansieht.
        stufe = opts.get("markierung", "gruendlich")
        fremd = {d.get("markierung", "unbekannt") for d in ergebnisse.values()
                 if d.get("markierung", stufe) != stufe}
        if fremd:
            console.print(
                f"[bold red]Abbruch:[/bold red] {json_out.name} enthält Ergebnisse "
                f"mit Markierung {', '.join(sorted(fremd))}, gerechnet werden soll "
                f"mit '{stufe}'. Entweder --markierung {sorted(fremd)[0]} setzen, "
                f"mit --neu neu rechnen, oder in eine andere Datei schreiben.")
            raise SystemExit(1)
        # Dasselbe für Modell, Schwelle, Musterlastenheft und Entscheider. Ältere
        # Ergebnisse ohne Steckbrief lassen sich nicht prüfen und bleiben stehen.
        erwartet = _erwartete_bedingungen(model, min_score, standard, opts)
        abweichend: dict[str, set[str]] = {}
        for lh, d in ergebnisse.items():
            for feld in _abweichende_bedingungen(d, erwartet):
                abweichend.setdefault(feld, set()).add(lh)
        if abweichend:
            zeilen = "\n".join(f"  {feld}: {', '.join(sorted(lhs))}"
                               for feld, lhs in sorted(abweichend.items()))
            console.print(
                f"[bold red]Abbruch:[/bold red] {json_out.name} enthält Ergebnisse "
                f"unter anderen Bedingungen als dieser Lauf:\n{zeilen}\n"
                f"  Mit --neu neu rechnen oder in eine andere Datei schreiben.")
            raise SystemExit(1)
        neben = _nebendatei(json_out)
        if neben.exists():
            try:
                offen_je_dok = json.loads(neben.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                offen_je_dok = {}

    for i, p in enumerate(dateien, start=1):
        if p.stem in ergebnisse:
            continue
        console.print(f"[{i}/{len(dateien)}] {p.stem} …")
        try:
            chunks = load_document(p, kind="neu")
        except TextExtraktionsFehler as e:
            console.print(f"    [red]übersprungen:[/red] {e}")
            continue
        ergebnis, details = evaluate_document(
            chunks, lh_id=p.stem, model=model, min_score=min_score,
            kriterien=kriterien, standard=standard, **opts)
        offen = nicht_bewertete(details)
        ergebnisse[p.stem]   = ergebnis
        offen_je_dok[p.stem] = len(offen)

        if json_out:
            # Atomar: Ein Abbruch mitten im Schreiben ließ sonst eine halbe Datei
            # zurück, und die nächste Wiederaufnahme begann von vorn.
            schreibe_json(json_out, ergebnisse)
            schreibe_json(_nebendatei(json_out), offen_je_dok)

        kz = ergebnis["kennzahlen"]
        console.print(f"    E {kz['entspricht']} · T {kz['teilweise']} · "
                      f"A {kz['abweichung']} · N {kz['keine_vorgabe']}"
                      + (f" · markiert {kz['markiert']}" if kz.get("markiert") else "")
                      + (f"  [red]{len(offen)} nicht bewertet[/red]" if offen else ""))
        if offen:
            console.print(f"      [dim]{offen[0][1][:110]}[/dim]", highlight=False)

    return ergebnisse, offen_je_dok


@cli.command("modelle")
@click.argument("namen", nargs=-1)
def modelle_command(namen):
    """Sprachmodelle auf Tauglichkeit prüfen, bevor ein Lauf gestartet wird.

    Ohne Angabe werden alle installierten Modelle geprüft. Die Prüfung kostet
    Sekunden und erspart einen einstündigen Lauf, dessen Ergebnis nur zeigt,
    dass der Prompt nicht ins Kontextfenster passte.
    """
    from src.auswertung.modelle import installierte_modelle, kurzfassung, pruefe_modelle

    liste = list(namen) or installierte_modelle()
    if not liste:
        console.print("[yellow]Keine Modelle gefunden. Läuft Ollama? "
                      f"Empfohlen: ollama pull {STANDARD_MODELL}[/yellow]")
        raise SystemExit(1)

    console.print(f"[bold]Anforderung:[/bold] Kontextfenster {NUM_CTX} Tokens "
                  f"(Prompt bis rund 4.900 + Antwort bis {NUM_PREDICT})\n")

    tauglich = 0
    for b in pruefe_modelle(liste):
        zeichen = "[green]✓[/green]" if b.ok else "[red]✗[/red]"
        console.print(f"{zeichen} {kurzfassung(b)}")
        for m in b.meldungen:
            console.print(f"    [dim]{m}[/dim]")
        for h in b.hindernisse:
            console.print(f"    [red]{h}[/red]")
        tauglich += b.ok

    console.print(f"\n{tauglich} von {len(liste)} Modell(en) tauglich.")
    raise SystemExit(0 if tauglich else 1)


@cli.command("modellvergleich")
@click.argument("pdf_folder", type=click.Path(exists=True))
@click.option("--model", "modelle_arg", multiple=True, required=True,
              help="Modell, mehrfach angebbar")
@click.option("--limit", default=0,
              help="zusätzlich auf die ersten N kürzen — zum Abbrechen von "
                   "Probeläufen; zum Sieben besser --teil stichprobe")
@click.option("--out", type=click.Path(), default="output/modellvergleich",
              help="Präfix für die Zwischenstände je Modell. Vorgabe liegt in "
                   "output/, weil die Dateien Begründungen aus den "
                   "Kundenlastenheften enthalten und nicht ins Repository dürfen")
@click.option("--min-score", default=MIN_SCORE, help="Relevanzschwelle (0.0-1.0)")
@click.option("--neu", is_flag=True, help="Zwischenstände verwerfen")
@click.option("--ohne-pruefung", is_flag=True,
              help="Modellprüfung überspringen und trotzdem laufen")
@click.option("--teil", type=click.Choice(["training", "stichprobe", "alle",
                                           "held-out"]),
              default="training",
              help="Korpusteil. Vorgabe 'training' (14 Dokumente); "
                   "'stichprobe' sind die festen fünf zum Sieben von Kandidaten")
def modellvergleich_command(pdf_folder: str, modelle_arg, limit: int, out: str,
                            min_score: float, neu: bool, ohne_pruefung: bool,
                            teil: str):
    """Mehrere Sprachmodelle auf demselben Korpus vergleichen.

    Jedes Modell läuft über dieselben Dokumente mit derselben Konfiguration.
    Zwischenstände werden je Modell gesichert, ein Abbruch kostet höchstens ein
    Dokument.

    Läuft standardmäßig auf dem TRAININGSTEIL. Ein Modell anhand der
    Held-out-Dokumente auszuwählen hieße, auf ihnen zu optimieren.

    Zum Sieben vieler Kandidaten `--teil stichprobe`: eine feste, kleine Auswahl.
    """
    from src.auswertung.evaluation import (
        format_bericht, format_mcnemar, korpus, load_ground_truth, mcnemar,
        vergleiche,
    )
    from src.auswertung.modelle import kurzfassung, pruefe_modelle

    kriterien = load_kriterien()
    standard  = load_standard()
    gt        = load_ground_truth()
    namen     = list(modelle_arg)

    if not ohne_pruefung:
        console.rule("[bold blue]Modellprüfung")
        befunde = pruefe_modelle(namen)
        for b in befunde:
            zeichen = "[green]✓[/green]" if b.ok else "[red]✗[/red]"
            console.print(f"{zeichen} {kurzfassung(b)}")
            for h in b.hindernisse:
                console.print(f"    [red]{h}[/red]")
        untauglich = [b.name for b in befunde if not b.ok]
        if untauglich:
            console.print(f"\n[red]Abbruch:[/red] {', '.join(untauglich)} "
                          f"würde(n) kein gültiges Ergebnis liefern. Mit "
                          f"--ohne-pruefung trotzdem starten.")
            raise SystemExit(1)

    erlaubt = set(korpus(gt, teil.replace("-", "_")))
    dateien = sorted(p for p in Path(pdf_folder).iterdir()
                     if p.is_file() and p.stem in erlaubt)
    if not dateien:
        console.print(f"[red]Keine Dokumente des Korpusteils '{teil}' in "
                      f"{pdf_folder}.[/red]")
        console.print("Erwartet: " + ", ".join(sorted(erlaubt)))
        raise SystemExit(1)
    if limit:
        dateien = dateien[:limit]

    console.print(f"\n[bold]{len(namen)} Modell(e) über {len(dateien)} "
                  f"Dokument(e) — Korpusteil '{teil}'[/bold]")
    if teil == "held-out":
        console.print("[bold yellow]Warnung: Ein Modell anhand der Held-out-"
                      "Dokumente auszuwählen macht deren Zahl wertlos. Nur "
                      "sinnvoll, wenn die Modellwahl bereits feststeht.[/bold yellow]")
    console.print("[dim]" + ", ".join(p.stem for p in dateien) + "[/dim]")

    laeufe: dict[str, dict] = {}
    dauern: dict[str, float] = {}
    offene: dict[str, int] = {}
    for name in namen:
        console.rule(f"[bold blue]{name}")
        ziel = Path(f"{out}_{name.replace(':', '-').replace('/', '-')}.json")
        ziel.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        laeufe[name], offen = lauf_ueber_dokumente(
            dateien, name, kriterien, standard, min_score=min_score,
            json_out=ziel, neu=neu, markierung="aus",
            mit_entscheider=False)
        dauern[name] = time.time() - t0
        # Fehlt zu einem übernommenen Dokument die Angabe, ist die Zahl
        # unbekannt — nicht null. Eine erfundene Null wäre hier schlimmer als
        # ein Fragezeichen: Sie behauptete einen fehlerfreien Lauf.
        offene[name] = (sum(offen.values())
                        if set(offen) >= set(laeufe[name]) else None)

    # ── Gegenüberstellung ────────────────────────────────────────────────
    evs = {n: vergleiche(l, kriterien, gt) for n, l in laeufe.items() if l}
    if not evs:
        console.print("[red]Kein Modell hat ein Ergebnis geliefert.[/red]")
        raise SystemExit(1)

    console.rule("[bold blue]Gegenüberstellung")
    # Kurze Spaltenköpfe: Mit ausgeschriebenen Namen bricht die Tabelle in
    # einem normalen Terminalfenster um und wird unlesbar.
    t = Table(show_header=True, header_style="bold")
    t.add_column("Modell", width=18, no_wrap=True)
    for spalte, breite in (("EM", 7), ("Prec", 7), ("Rec", 7), ("F1", 7),
                           ("Pflicht", 8), ("A", 7), ("offen", 6), ("min", 5)):
        t.add_column(spalte, justify="right", width=breite, no_wrap=True)

    rangfolge = sorted(evs, key=lambda n: evs[n]["exact_match"], reverse=True)
    for n in rangfolge:
        ev = evs[n]
        g  = ev["geregelt_erkannt"]
        c  = ev["_conf_raw"]
        ref_a = sum(c[("A", s)] for s in STATUS_WERTE)
        pflicht = ev["je_einstufung"].get("Pflicht", {}).get("quote", 0)
        o = offene.get(n)
        t.add_row(n, f"{ev['exact_match']:.1%}", f"{g['precision']:.1%}",
                  f"{g['recall']:.1%}", f"{g['f1']:.1%}", f"{pflicht:.1%}",
                  f"{c[('A', 'A')]}/{ref_a}", "?" if o is None else str(o),
                  f"{dauern[n]/60:.0f}")
    console.print(t)
    console.print(f"[dim]EM Exact Match · Prec/Rec/F1 geregelt erkannt · "
                  f"Pflicht Trefferquote bei Pflichtkriterien · A erkannte "
                  f"Abweichungen · offen nicht bewertete Kriterien[/dim]")
    console.print(f"[dim]Baseline immer E: "
                  f"{evs[rangfolge[0]]['baselines']['immer_E']:.1%}[/dim]")

    belastet = [n for n in rangfolge if offene.get(n)]
    if belastet:
        console.print("\n[bold red]Nicht bewertete Kriterien:[/bold red] "
                      + ", ".join(f"{n} ({offene[n]})" for n in belastet)
                      + " — dort hat das Modell nicht verwertbar geantwortet. "
                        "Diese Fälle stehen als N in der Auswertung und "
                        "verfälschen alle Kennzahlen des betroffenen Modells.")
    unbekannt = [n for n in rangfolge if offene.get(n) is None]
    if unbekannt:
        console.print(f"\n[yellow]Für {', '.join(unbekannt)} ist unbekannt, wie "
                      f"viele Kriterien unbewertet blieben[/yellow] — die "
                      f"Ergebnisse stammen aus einem früheren Lauf ohne diese "
                      f"Angabe. Mit --neu neu rechnen, wenn es darauf ankommt.")

    # ── Gepaarter Test gegen das beste Modell ────────────────────────────
    if len(rangfolge) > 1:
        console.rule("[bold blue]Ist der Unterschied belastbar?")
        console.print("[dim]McNemar über dieselben Testfälle. Entscheidend ist "
                      "nicht die Differenz, sondern wie oft die Läufe "
                      "auseinanderlaufen.[/dim]\n")
        bester = rangfolge[0]
        for n in rangfolge[1:]:
            m = mcnemar(laeufe[bester], laeufe[n], kriterien, gt)
            console.print(format_mcnemar(m, bester, n) + "\n")

    console.rule(f"[bold blue]Bester Lauf: {rangfolge[0]}")
    console.print(format_bericht(evs[rangfolge[0]]))


@cli.command("list-models")
def list_models_command():
    """Verfügbare Ollama-Modelle anzeigen."""
    from src.auswertung.modelle import installierte_modelle

    namen = installierte_modelle()
    if not namen:
        console.print(f"[yellow]Keine Ollama-Modelle installiert. "
                      f"Empfohlen: ollama pull {STANDARD_MODELL}[/yellow]")
        return
    console.print("[bold]Installierte Ollama-Modelle:[/bold]")
    for name in namen:
        console.print(f"  - {name}")
