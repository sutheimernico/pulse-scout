# pulse-scout — Arbeitsweise & Locked Decisions

Globale persönliche Regeln (`~/.claude/CLAUDE.md`) gelten. Diese Datei ergänzt projekt-spezifisch.
Source of Truth: `PROJECT.md` — when this file and PROJECT.md disagree, PROJECT.md wins.
Codebase operations (stack, architecture, run/build/test): `AGENTS.md`.

## Locked decisions (2026-08-07) — full register in PROJECT.md §Decisions

- **Zweistufiger Digest.** Pflicht mit echter Einordnung, Kür als Einzeiler. Fünf Minuten
  reichen für 12–20 Kurzitems insgesamt, nicht pro Thema.
- **Der Digest wird lokal geschrieben, nicht über die Claude-API.** Claude hat zweimal mit
  Messwerten dagegen argumentiert (~30 Min CPU-Last gegen ~8 Sekunden und ~3 €/Monat); Nico
  hat sich bewusst dagegen entschieden. **Nicht erneut aufmachen**, außer Nico fängt an.
- **Fäden über Embeddings, nicht über das Sprachmodell.** Genau die Schwäche eines 7B-Modells;
  Kosinus-Ähnlichkeit beantwortet „gleiches Thema?" deterministisch und in Millisekunden.
- **PWA nach dem equity-scout-Muster**, keine native App. Das Muster läuft schon auf dieser
  Maschine.
- **Themen eingegrenzt:** KI-Modelle zuerst, Azure zweitens. Product/Design/Marketing und dbt
  sind raus — die ersten drei haben verifiziert kein Tagesvolumen, dbt ist nicht Nicos Feld.
- **Durchsatz ist die bindende Grenze.** Gemessen: 18,1 Token/s Einlesen, 4,5 Token/s Schreiben,
  reine CPU. Jede Vergrößerung von Kontext oder Ausgabe kostet echte Minuten pro Tag.

## Wie Claude hier arbeitet

- **Flow:** Trivial → direkt. Sonst Superpowers: `brainstorming` → `writing-plans` (Go abwarten) →
  `executing-plans`/`subagent-driven-development` → `verification-before-completion`.
- **Orchestrierung:** Read/Recherche/Review/Sweeps an Subagents (nur Konklusion zurück).
  Write/Build mit Abhängigkeiten single-threaded inline.
- **Self-Review:** iterativ pro Arbeitsschritt, nicht erst vor dem PR.
- **Vor Änderungen an der Quellenliste:** die betroffene URL wirklich abrufen. Die halluzinierte
  Feed-Adresse ist der häufigste Fehler in diesem Projekt — `data/sources.toml` enthält unten
  eine Liste dessen, was nachweislich nicht funktioniert. Nichts davon ohne neuen Test zurückholen.

## Conventions

- Code, Bezeichner, Kommentare, Commits, Doku Englisch; Chat und UI-Texte Deutsch.
- Conventional Commits. Nie direkt auf `main` — Branch (`feat/…`, `fix/…`, Loop: `autopilot/work`).
- Neue Logik kommt mit Test. Netz- und Ollama-Code hinter Seam, in Tests gefakt.
- Gate vor jedem Commit: `uv run pytest -q` grün **und** `uv run ruff check .` sauber.

## Ehrlichkeit (das Produkt ist ein Vertrauensversprechen)

Der ganze Wert liegt darin, dass Nico dem Digest glauben kann. Deshalb:

- Keine erfundenen Meldungen, Quellen oder Zahlen. Ein Lauf ohne brauchbares Ergebnis schlägt
  sichtbar fehl, statt etwas Plausibles zu erzeugen.
- Beispiel-/Mock-Daten immer sichtbar als solche kennzeichnen — in der UI und in der Antwort.
- Der Trichterzähler oben im Screen (`412 gesichtet → 5 für dich`) muss echte Zahlen zeigen.

## Plan, spec & session docs

- Specs: `docs/superpowers/specs/YYYY-MM-DD-*.md` · Pläne: `docs/superpowers/plans/YYYY-MM-DD-*.md`
- Session-Handoffs: `docs/sessions/YYYY-MM-DD_HHMM_<topic>.md`
- ADRs: `docs/adr/NNNN-<slug>.md`
- Doku ist committed.
