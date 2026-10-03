"""„Warum dieses Urteil?" — der Weg eines Kriteriums, Schritt für Schritt.

## Wozu

Ein Prüfbericht, der nur das Ergebnis zeigt, ist bei begrenzter Treffergenauigkeit
nicht überprüfbar. Wer bei einem Kriterium „keine Vorgabe" liest, kann heute
nicht unterscheiden, ob

  * die Suche nichts über der Relevanzschwelle gefunden hat,
  * das Modell die vorgelegten Stellen für nicht einschlägig hielt,
  * das Modell etwas geantwortet hat, das sich nicht lesen ließ,
  * oder die Belegpflicht (R1) ein E, T oder A stillschweigend auf N
    heruntergestuft hat.

Das sind vier verschiedene Fehler mit vier verschiedenen Antworten darauf. Diese
Ansicht trennt sie.

## Warum nicht LangSmith

Dieselbe Funktion gibt es fertig — LangSmith zeigt Prompt, Antwort, Laufzeit und
fehlgeschlagene Parses in einer Weboberfläche. Sie ist nur ein Cloud-Dienst:
Jeder Prompt und jede Antwort ginge an fremde Server. Bei 68 Aufrufen je
Dokument, in denen jeweils bis zu 30 Textstellen aus dem Kundenlastenheft und
ein Abschnitt des Musterlastenhefts stehen, wäre das exakt die Übertragung, die
das Briefing ausschließt.

Deshalb hier: dieselbe Auskunft, lokal, aus Daten, die beim Prüflauf ohnehin
anfallen.

## Was NICHT hier steht

Die Ansicht erklärt nicht, warum ein Sprachmodell so entschieden hat — das kann
sie nicht. Sie zeigt, was hineinging und was herauskam. Der Schluss bleibt beim
Leser.
"""

from __future__ import annotations

import html as _html
import json

import streamlit as st

from ui.design import STATUS_TEXT, status_tag

# Reihenfolge der Stationen. Sie ist die Reihenfolge im Programm — wer sie
# ändert, muss evaluate_document ändern, nicht diese Liste.
STATIONEN = ("Suche", "Prompt", "Antwort", "Belegpflicht", "Herkunft", "Ergebnis")


def _kurz(text: str, n: int = 400) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n].rstrip() + " …"


def lage(detail: dict, bewertung: dict) -> tuple[str, str]:
    """Was ist mit diesem Kriterium passiert? (Kurzform, Begründung)

    Die vier Fälle aus dem Modulkopf, in der Reihenfolge, in der sie im
    Programm auftreten. Reine Auswertung des Mitschnitts — kein Rechnen.
    """
    detail = detail or {}
    status = (bewertung or {}).get("status", "N")
    kandidaten = detail.get("kandidaten") or []
    grund = (detail.get("grund") or "").strip()
    geparst = detail.get("geparst")

    if grund and not kandidaten:
        return ("Suche ohne Treffer",
                "Es lag keine Textstelle über der Relevanzschwelle vor. Das "
                "Modell wurde für dieses Kriterium gar nicht erst gefragt.")
    if grund:
        return ("Modellaufruf gescheitert",
                f"Der Aufruf kam nicht verwertbar zurück: {grund}. Das Kriterium "
                "steht als „keine Vorgabe“ im Bericht, ist aber in Wahrheit "
                "**ungeprüft**.")

    # Nach der Prüfung auf A gehoben (src/pruefung/markierung.py). Die Belegpflicht hat
    # dann nicht eingegriffen — verglichen wird mit dem Status des Modells.
    if (bewertung or {}).get("status_modell"):
        herkunft = " · ".join(bewertung.get("herkunft") or [])
        return ("Nachträglich als Abweichung markiert",
                f"Das Modell hat **{bewertung['status_modell']}** vergeben. Wegen "
                f"der Anzeichen **{herkunft}** steht **A** im Bericht — zur "
                f"Durchsicht, nicht als Urteil des Modells.")

    if (bewertung or {}).get("gehoben"):
        p = (detail.get("entscheider") or {})
        return ("Statistisch gehoben",
                f"Das Modell hat **N** vergeben. Der gelernte Entscheider hält nach den "
                f"Suchmerkmalen **{bewertung.get('status')}** für wahrscheinlicher "
                f"({float(bewertung.get('p_entscheider') or 0):.0%}"
                + (f", N {p.get('N', 0):.0%}" if p else "") + "). Die Begründung stammt "
                f"nicht vom Modell — die Stellen unten sind der Ort zum Nachsehen.")

    if geparst and geparst.get("status") != status:
        return ("Von der Belegpflicht geändert",
                f"Das Modell hat **{geparst.get('status')}** geantwortet. Regel R1 "
                f"verlangt zu jedem E, T und A eine Begründung und eine "
                f"Seitenzahl; hier fehlte etwas davon, deshalb steht "
                f"**{status}** im Bericht.")

    # Vor „regulär eingestuft“, aber nach der Belegpflicht: Der Status stimmt
    # womöglich, die Begründung nennt aber etwas, das nur im Prompt steht.
    if detail.get("echo"):
        genannt = ", ".join(detail["echo"][:4])
        return ("Begründung teilweise aus dem Prompt",
                f"Die Begründung nennt **{genannt}** — das steht nicht im "
                f"Kundendokument, sondern im Musterlastenheft-Abschnitt des "
                f"Prompts. Das Urteil **{status}** kann trotzdem richtig sein; "
                f"nachprüfbar ist die Begründung an dieser Stelle nicht.")

    if status == "N" and kandidaten:
        return ("Stellen gefunden, nicht als Vorgabe gewertet",
                f"Die Suche hat {len(kandidaten)} Stellen vorgelegt. Das Modell "
                "hielt keine davon für eine Regelung zu diesem Punkt. Genau hier "
                "sitzt der häufigste Fehler der Software — die vorgelegten "
                "Stellen unten sind der Ort zum Nachsehen.")

    return ("Regulär eingestuft",
            f"Die Suche hat {len(kandidaten)} Stellen vorgelegt, das Modell hat "
            f"daraus **{status} — {STATUS_TEXT.get(status, '')}** gemacht.")


def _stelle(i: int, k: dict) -> None:
    seite = k.get("page")
    kopf = f"Rang {i} · Seite {seite}" if seite is not None else f"Rang {i}"
    wert = k.get("score")
    if wert is not None:
        kopf += f" · Ähnlichkeit {float(wert):.3f}"
    st.markdown(f'<span class="krit-seite">{_html.escape(kopf)}</span>',
                unsafe_allow_html=True)
    st.markdown(f'<pre class="krit-beleg">'
                f'{_html.escape((k.get("text") or "").strip())}</pre>',
                unsafe_allow_html=True)


def render(details: dict, kriterien: list[dict], ergebnis: dict) -> None:
    """Die Ansicht. `details` kommt aus evaluate_document, zweiter Rückgabewert."""
    if not details:
        st.info("Für diesen Lauf liegt kein Mitschnitt vor.")
        return

    bewertungen = (ergebnis or {}).get("bewertungen", {})
    titel = {k["nr"]: k["titel"] for k in kriterien}

    # Auffälliges zuerst: Was ungeprüft blieb oder von R1 geändert wurde, ist
    # der Grund, warum jemand diese Ansicht überhaupt öffnet.
    auffaellig = []
    for nr in titel:
        kurz, _ = lage(details.get(nr), bewertungen.get(nr))
        if kurz in ("Modellaufruf gescheitert", "Von der Belegpflicht geändert",
                    "Begründung teilweise aus dem Prompt"):
            auffaellig.append(f"{nr} — {kurz}")
    if auffaellig:
        st.warning("**Auffällig in diesem Lauf:**\n\n"
                   + "\n".join(f"- {a}" for a in auffaellig))

    nummern = [k["nr"] for k in kriterien if k["nr"] in details]
    if not nummern:
        st.info("Für diesen Lauf liegt kein Mitschnitt vor.")
        return

    gewaehlt = st.selectbox(
        "Kriterium", nummern,
        format_func=lambda n: f"{n}  {titel.get(n, '')}",
        key="spur_kriterium")

    detail = details.get(gewaehlt) or {}
    bewertung = bewertungen.get(gewaehlt) or {}
    kandidaten = detail.get("kandidaten") or []
    kurz, warum = lage(detail, bewertung)

    st.markdown(f"{status_tag(bewertung.get('status', 'N'))} "
                f"&nbsp;**{_html.escape(kurz)}**", unsafe_allow_html=True)
    st.markdown(warum)

    # ── 1. Suche ──────────────────────────────────────────────────────────
    with st.expander(f"1 · Was die Suche vorgelegt hat ({len(kandidaten)} Stellen)",
                     expanded=not kandidaten):
        if not kandidaten:
            st.markdown("Keine Stelle über der Relevanzschwelle. Steht im Dokument "
                        "etwas dazu, ist es ein **Suchfehler**, kein Urteilsfehler.")
        else:
            st.caption("Reihenfolge wie im Prompt.",
                       help="Das Modell sah genau diesen Text, nicht das ganze Dokument.")
            for i, k in enumerate(kandidaten, start=1):
                _stelle(i, k)

    # ── 2. Prompt ─────────────────────────────────────────────────────────
    prompt = detail.get("prompt") or ""
    with st.expander("2 · Was das Modell gefragt wurde", expanded=False):
        if not prompt:
            st.markdown("Für diesen Lauf wurde der Prompt nicht mitgeschrieben "
                        "(Ergebnis aus einer früheren Fassung).")
        else:
            st.caption(f"{len(prompt):,} Zeichen".replace(",", "."),
                       help="Regeln, Musterlastenheft-Abschnitt und die Stellen von oben.")
            st.code(prompt, language=None)

    # ── 3. Antwort ────────────────────────────────────────────────────────
    with st.expander("3 · Was das Modell geantwortet hat", expanded=False):
        roh = detail.get("raw") or ""
        if not roh:
            st.markdown(f"Keine verwertbare Antwort. Grund: "
                        f"`{detail.get('grund') or 'unbekannt'}`")
        else:
            st.code(roh, language="json")
            geparst = detail.get("geparst")
            if geparst:
                st.caption("Daraus gelesen:")
                st.code(json.dumps(geparst, ensure_ascii=False, indent=2),
                        language="json")

    # ── 4. Belegpflicht ───────────────────────────────────────────────────
    geparst = detail.get("geparst")
    if geparst:
        # Verglichen wird mit dem Status VOR Entscheider und Markierung.
        vergleich = ("N" if bewertung.get("gehoben")
                     else bewertung.get("status_modell") or bewertung.get("status"))
        geaendert = geparst.get("status") != vergleich
        with st.expander(
                "4 · Belegpflicht (R1) — "
                + ("**hat eingegriffen**" if geaendert else "unverändert"),
                expanded=geaendert):
            st.caption("Regel R1", help="Ein E, T oder A braucht Begründung und "
                       "Seitenzahl. Fehlt die Begründung, wird daraus N; fehlt nur die "
                       "Seitenzahl, wird die des besten Kandidaten eingesetzt.")
            a, b = st.columns(2)
            a.markdown("**Modell sagte**")
            a.code(json.dumps(geparst, ensure_ascii=False, indent=2), language="json")
            b.markdown("**Im Bericht steht**")
            b.code(json.dumps(bewertung, ensure_ascii=False, indent=2), language="json")

    # ── 5. Herkunft der Begründung ────────────────────────────────────────
    echo = detail.get("echo")
    if echo is not None and bewertung.get("status", "N") != "N":
        with st.expander(
                "5 · Herkunft der Begründung — "
                + ("**Angabe stammt aus dem Prompt**" if echo else "unauffällig"),
                expanded=bool(echo)):
            st.caption("Stehen Zahlen, Normen und Typen der Begründung im Dokument?",
                       help="Steht eine Angabe nur im Musterlastenheft-Abschnitt des "
                            "Prompts, hat das Modell abgeschrieben statt gelesen.")
            if echo:
                st.markdown("**Nur im Prompt gefunden:** "
                            + ", ".join(f"`{_html.escape(a)}`" for a in echo))
                st.caption("Status unverändert — nur gekennzeichnet.")
            else:
                st.caption("Nichts nachweislich aus dem Prompt.",
                           help="Das heißt nicht, dass die Begründung stimmt — nur, "
                                "dass sich das Gegenteil hier nicht zeigt.")


def kopf() -> None:
    st.markdown("**Nachvollziehen**",
                help="Der Weg eines Kriteriums: vorgelegte Stellen, Prompt, Antwort "
                     "des Modells und was daraus im Bericht wurde. Alles lokal.")
