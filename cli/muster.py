"""Befehle zum Musterlastenheft: Einordnung und Musteraufbau."""

import click
from pathlib import Path

from src.pruefung.kriterien import STANDARD_MODELL, load_kriterien, load_standard
from cli.basis import cli, console


@cli.command("standardhaltung")
@click.option("--model", default=None, help="Sprachmodell (Vorgabe: Standardmodell)")
def standardhaltung_command(model: str | None):
    """Den Standard einmalig danach einordnen, wie er es mit Herstellern hält.

    Der Hinweis-Durchgang fragt nur die Kriterien, an denen eine
    Fabrikatsbindung des Kunden überhaupt bedeutsam sein kann. Diese Auswahl
    besorgt sonst ein Regex; mit dieser Einordnung wird sie kleiner und genauer.

    Läuft EINMAL je Musterlastenheft, nicht je Dokument. Wird der Standard
    ausgetauscht, verfällt die Einordnung von selbst und der Regex übernimmt
    wieder — dann diesen Befehl erneut aufrufen.
    """
    from src.pruefung.kriterien import STANDARD_MODELL, _chat, load_kriterien, load_standard
    from src.pruefung.standardhaltung import HALTUNGSDATEI, einordnen

    standard = load_standard()
    if not standard:
        console.print("[red]Kein Musterlastenheft hinterlegt.[/red]")
        raise SystemExit(1)
    kriterien = load_kriterien()
    gewaehlt = model or STANDARD_MODELL
    console.print(f"[bold]Ordne {len(kriterien)} Abschnitte ein[/bold] "
                  f"mit {gewaehlt}")

    def on_progress(i: int, n: int, name: str):
        console.print(f"  [{i:>2}/{n}] {name}", highlight=False)

    erg = einordnen(standard, kriterien, gewaehlt, _chat,
                    fortschritt=on_progress)
    from collections import Counter
    z = Counter(v["einordnung"] for v in erg.values())
    for klasse in ("VORGESCHRIEBEN", "DELEGIERT", "SCHWEIGT"):
        console.print(f"  {klasse:<16} {z.get(klasse, 0):>3}")
    im_filter = z.get("DELEGIERT", 0) + z.get("VORGESCHRIEBEN", 0)
    console.print(f"[green]{im_filter} von {len(kriterien)} Kriterien im "
                  f"Vorfilter.[/green] Gespeichert: {HALTUNGSDATEI.name}")


@cli.command("kalibrieren")
@click.argument("ordner", type=click.Path(exists=True, file_okay=False))
@click.option("--ground-truth", "gt_pfad", type=click.Path(exists=True, dir_okay=False),
              default=None, help="Referenzbewertungen (Vorgabe: aktive Fassung, GT_ABGLEICH in src/verzeichnisse.py)")
def kalibrieren_command(ordner: str, gt_pfad: str | None):
    """Den Entscheider für das aktive Musterlastenheft trainieren.

    ORDNER enthält bewertete Lastenhefte; ihre Dateinamen ohne Endung sind die
    Kennungen in den Referenzbewertungen. Braucht kein Sprachmodell — gelernt wird
    aus Suche und Referenz. Nötig nach einem neuen Musterlastenheft, einem anderen
    Einbettungsmodell oder geänderten Sucheinstellungen; ein anderes Sprachmodell
    braucht es nicht. Siehe src/pruefung/entscheider.py.
    """
    import json
    from collections import Counter

    from src.muster import bibliothek
    from src.pruefung import entscheider as EN
    from src.verzeichnisse import GT_ABGLEICH

    standard = load_standard()
    if not standard:
        console.print("[red]Kein Musterlastenheft hinterlegt.[/red]")
        raise SystemExit(1)
    pfad = Path(gt_pfad) if gt_pfad else GT_ABGLEICH
    try:
        gt = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        console.print(f"[red]Referenzbewertungen nicht lesbar: {e}[/red]")
        raise SystemExit(1)

    zeilen: list = []
    X, y, dokumente = EN.lernzeilen(
        Path(ordner), gt, load_kriterien(), standard,
        fortschritt=lambda i, n, name: console.print(f"  [{i:>2}/{n}] {name}", highlight=False),
        zeilen=zeilen)
    if len(dokumente) < 5:
        console.print(f"[red]Nur {len(dokumente)} bewertete Lastenhefte gefunden — zu wenig "
                      f"zum Trainieren (mindestens 5).[/red]")
        raise SystemExit(1)
    modell = EN.trainieren(X, y, standard, dokumente)
    try:
        modell["rangierer"] = EN.rangierer_trainieren(zeilen, standard)
    except ValueError as e:
        console.print(f"[yellow]Rangierer für „gründlich“ nicht trainiert: {e}[/yellow]")
    ziel = EN.speichern(modell)
    bibliothek.zuruecksichern()
    console.print(f"[green]Entscheider trainiert[/green] aus {len(dokumente)} Lastenheften, "
                  f"{len(y)} Fällen {dict(Counter(y))} → {ziel.name}")
    if len(dokumente) < 17:
        console.print("[yellow]Der Entscheider ist für deutlich mehr Trainingsdokumente "
                      "ausgelegt. Mit wenigen ist seine Güte unbekannt.[/yellow]")


@cli.command("entscheider-uebertragen")
@click.argument("von")
def entscheider_uebertragen_command(von: str):
    """Den Entscheider eines anderen hinterlegten Musterlastenhefts für das aktive übernehmen.

    VON ist der Schlüssel des Bibliothekseintrags, etwa „druckgiesswerkzeuge“. Gedacht
    für ein neues Anwendungsfeld, solange die bewerteten Lastenhefte für `kalibrieren`
    fehlen.
    """
    import json

    from src.muster import bibliothek
    from src.pruefung import entscheider as EN

    standard = load_standard()
    if not standard:
        console.print("[red]Kein Musterlastenheft hinterlegt.[/red]")
        raise SystemExit(1)
    eintraege = {e.schluessel: e for e in bibliothek.eintraege()}
    if von not in eintraege:
        console.print(f"[red]Kein Musterlastenheft „{von}“ in der Bibliothek.[/red] "
                      f"Vorhanden: {', '.join(sorted(eintraege))}")
        raise SystemExit(1)
    quelle = eintraege[von]
    if quelle.aktiv:
        console.print("[red]Das ist das aktive Musterlastenheft selbst.[/red] Erst das "
                      "Ziel aktivieren, dann übertragen.")
        raise SystemExit(1)
    datei = quelle.ordner / EN.DATEI.name
    try:
        modell = json.loads(datei.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        console.print(f"[red]„{quelle.name}“ hat keinen lesbaren Entscheider.[/red]")
        raise SystemExit(1)
    if modell.get("merkmale") != list(EN.MERKMALE):
        console.print("[red]Der Entscheider ist mit anderen Merkmalen trainiert.[/red]")
        raise SystemExit(1)
    ziel = EN.speichern(EN.uebertragen(modell, standard, quelle.name))
    bibliothek.zuruecksichern()
    console.print(f"[green]Entscheider von „{quelle.name}“ übernommen[/green] → {ziel.name}")
    console.print("[yellow]Nicht für dieses Musterlastenheft trainiert. Sobald "
                  "fünf bewertete Lastenhefte vorliegen, mit `kalibrieren` ersetzen.[/yellow]")


@cli.command("muster-vorschlag")
@click.option("--ordner", type=click.Path(file_okay=False), default=None,
              help="Arbeitsordner (Vorgabe: data/musteraufbau). Lastenhefte in <ordner>/dokumente.")
@click.option("--gegenstand", required=True,
              help="Anwendungsfeld in der Mehrzahl, z. B. „Schaltschränke“.")
@click.option("--model", default=None, help="Lokales Sprachmodell (Vorgabe: Standardmodell)")
def muster_vorschlag_command(ordner: str | None, gegenstand: str, model: str | None):
    """Schritt 1 des Musteraufbaus: Gliederung aus den Lastenheften vorschlagen.

    Das Ergebnis ist ein Vorschlag zum Prüfen (gliederung.json), keine fertige
    Gliederung. Danach in der Oberfläche prüfen und `muster-aufbauen` starten.
    """
    from src.muster import musteraufbau as MA

    modell = model or MA.MODELL
    stand = MA.Arbeitsstand(Path(ordner)) if ordner else MA.Arbeitsstand()
    if not stand.dateien():
        console.print(f"[red]Keine Lastenhefte in {stand.dokumente}.[/red]")
        raise SystemExit(1)
    console.print(f"[bold]Gliederung vorschlagen[/bold] aus {len(stand.dateien())} "
                  f"Lastenheften · {gegenstand} · {modell}")
    MA.lauf_vorschlag(stand, gegenstand, modell)
    f = stand.lesen(stand.fortschritt, {})
    console.print(f"[green]{f.get('text')}[/green] → {stand.gliederung}")


@cli.command("muster-aufbauen")
@click.option("--ordner", type=click.Path(file_okay=False), default=None,
              help="Arbeitsordner (Vorgabe: data/musteraufbau)")
@click.option("--model", default=None, help="Lokales Sprachmodell (Vorgabe: Standardmodell)")
def muster_aufbauen_command(ordner: str | None, model: str | None):
    """Schritt 3 des Musteraufbaus: Inhalte erzeugen und Word-Entwurf schreiben.

    Setzt nach einem Abbruch auf den bereits erzeugten Kriterien auf.
    """
    from src.muster import musteraufbau as MA

    modell = model or MA.MODELL
    stand = MA.Arbeitsstand(Path(ordner)) if ordner else MA.Arbeitsstand()
    ziel = MA.lauf_inhalte(stand, modell)
    console.print(f"[green]Entwurf geschrieben:[/green] {ziel}")
