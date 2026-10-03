"""Prüfung von Sprachmodellen, bevor ein Vergleichslauf gestartet wird.

Ein voller Lauf über die 18 Lastenhefte dauert rund eine Stunde. Ein Modell,
dessen Kontextfenster nicht reicht, liefert dabei ein Ergebnis, das aussieht wie
schlechte Modellqualität und in Wahrheit ein abgeschnittener Prompt ist: Ollama
kürzt stillschweigend von vorne, und vorne steht die Standardanforderung.

Diese Prüfung kostet Sekunden und erspart genau diesen Fehlschluss. Sie
beantwortet drei Fragen:

- Ist das Modell überhaupt installiert?
- Nimmt es das benötigte Kontextfenster an?
- Ist es ein Reasoning-Modell? Dann muss `think=False` gesetzt werden, sonst
  verbraucht es das Antwortbudget mit Denken und liefert leeren Text.
"""

import inspect
from dataclasses import dataclass, field

import ollama

from src.pruefung.kriterien import NUM_CTX, NUM_PREDICT

_THINK_SUPPORTED = "think" in inspect.signature(ollama.chat).parameters


@dataclass
class Modellbefund:
    """Was über ein Modell bekannt ist, bevor es losläuft."""
    name:           str
    installiert:    bool = False
    kontext:        int | None = None
    parameter:      str = ""
    familie:        str = ""
    quantisierung:  str = ""
    denkt:          bool = False
    meldungen:      list[str] = field(default_factory=list)
    hindernisse:    list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.installiert and not self.hindernisse


def _felder(info) -> dict:
    return info if isinstance(info, dict) else info.model_dump()


def installierte_modelle() -> list[str]:
    """Namen der lokal vorhandenen Modelle. Leere Liste, wenn Ollama nicht läuft."""
    try:
        return sorted(m.model for m in ollama.list().models)
    except Exception:
        return []


def pruefe_modell(name: str, benoetigt_ctx: int = NUM_CTX) -> Modellbefund:
    """Prüft ein einzelnes Modell gegen die Anforderungen des Prüflaufs."""

    b = Modellbefund(name=name)

    try:
        info = _felder(ollama.show(name))
    except Exception as e:
        text = str(e)
        if "not found" in text.lower():
            b.hindernisse.append(f"nicht installiert — `ollama pull {name}`")
        else:
            b.hindernisse.append(f"nicht abfragbar: {text[:120]}")
        return b

    b.installiert = True

    mi = info.get("modelinfo") or info.get("model_info") or {}
    # Der Schlüssel trägt den Architekturnamen: qwen35.context_length,
    # llama.context_length, gemma3.context_length …
    for schluessel, wert in mi.items():
        if schluessel.endswith(".context_length") and isinstance(wert, int):
            b.kontext = wert
            break
    b.familie = str(mi.get("general.architecture") or "")

    details = info.get("details")
    if details:
        d = _felder(details)
        b.parameter     = str(d.get("parameter_size") or "")
        b.quantisierung = str(d.get("quantization_level") or "")
        b.familie       = b.familie or str(d.get("family") or "")

    faehigkeiten = info.get("capabilities") or []
    b.denkt = "thinking" in faehigkeiten

    if b.kontext is None:
        b.meldungen.append(
            "Kontextfenster nicht auslesbar. Der Lauf ist trotzdem möglich, aber "
            "eine stille Kürzung des Prompts lässt sich nicht ausschließen.")
    elif b.kontext < benoetigt_ctx:
        b.hindernisse.append(
            f"Kontextfenster {b.kontext} Tokens, gebraucht werden "
            f"{benoetigt_ctx}. Der Prompt würde vorne abgeschnitten — dort steht "
            f"die Standardanforderung. Entweder ein anderes Modell wählen oder "
            f"die Zahl der Fundstellen senken.")

    if b.denkt and not _THINK_SUPPORTED:
        b.hindernisse.append(
            "Reasoning-Modell, aber die installierte ollama-Bibliothek kennt den "
            "Parameter `think` nicht (nötig ab 0.5). Das Modell verbraucht sonst "
            "das Antwortbudget mit Denken und liefert leeren Text. "
            "`pip install -U ollama`")
    elif b.denkt:
        b.meldungen.append("Reasoning-Modell — Denken wird abgeschaltet.")

    return b


def pruefe_modelle(namen: list[str], benoetigt_ctx: int = NUM_CTX
                   ) -> list[Modellbefund]:
    """Mehrere Modelle prüfen. Reihenfolge bleibt erhalten."""
    return [pruefe_modell(n, benoetigt_ctx) for n in namen]


def kurzfassung(b: Modellbefund) -> str:
    """Eine Zeile je Modell, für Terminal und Oberfläche."""
    if not b.installiert:
        return f"{b.name}: nicht verfügbar"
    teile = [t for t in (b.parameter, b.quantisierung, b.familie) if t]
    ctx = f"{b.kontext:,} Tokens".replace(",", ".") if b.kontext else "Kontext unbekannt"
    return f"{b.name}: {' · '.join(teile)} · {ctx}"


def antwortbudget_reicht(b: Modellbefund, prompt_tokens: int,
                         num_predict: int = NUM_PREDICT) -> bool:
    """Passen Prompt und Antwort zusammen ins Fenster?

    `num_ctx` gilt für beides zusammen. Diese Verwechslung hat in diesem Projekt
    schon einmal zu einer falschen Ursachenanalyse geführt: Ein Lauf lieferte
    67-mal „keine Vorgabe", und ich hielt die Antwortlänge für die Ursache,
    während in Wahrheit Prompt plus Antwort exakt das Fenster ausschöpften.
    """
    if b.kontext is None:
        return True
    return prompt_tokens + num_predict <= b.kontext
