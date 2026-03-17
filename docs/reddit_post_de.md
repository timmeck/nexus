# Ich habe das erste funktionierende AI-to-AI Protokoll gebaut — Agents finden, verhandeln und bezahlen sich gegenseitig ohne Menschen

**TL;DR:** Ich habe Nexus gebaut, ein Open-Source-Protokoll mit dem AI-Agents sich gegenseitig finden, Konditionen verhandeln, Antworten verifizieren und Micropayments abwickeln — alles automatisch. Wie DNS + HTTPS + Payment Rails, aber fuer AI. 66 Tests, voll funktionsfaehig, MIT-lizenziert.

**GitHub:** https://github.com/timmeck/nexus

---

## Das Problem

Jedes AI-Agent-Framework (LangChain, CrewAI, AutoGen) baut Agents die mit Tools reden. MCP verbindet AI mit externen Services. Aber **es gibt kein Protokoll mit dem AI-Agents untereinander kommunizieren**.

Wenn dein Coding-Agent eine juristische Einschaetzung braucht, kann er nicht automatisch einen Jura-Agent finden, einen Preis verhandeln, die Anfrage senden, die Antwort verifizieren und bezahlen. Du musst jede Integration manuell verdrahten.

Google hat A2A (Agent-to-Agent) als Spec angekuendigt. Es ist ein PDF. Keine Implementierung. Kein funktionierender Code.

## Was ich gebaut habe

**Nexus** — ein funktionierendes AI-to-AI Protokoll mit 5 Layern:

| Layer | Was es tut | Vergleichbar mit... |
|---|---|---|
| **Discovery** | Agents registrieren Capabilities, Consumer finden sie | DNS |
| **Trust** | Reputation-Scoring nach jeder Interaktion | Zertifizierungsstelle |
| **Protocol** | Standardisiertes Request/Response Format | HTTP |
| **Routing** | Besten/guenstigsten/schnellsten Agent finden | BGP |
| **Federation** | Mehrere Nexus-Instanzen synchronisieren Agent-Registries | Email-Server |

Plus:
- **Micropayments** — Credit-System, Pay-per-Request
- **Multi-Agent Verification** — 3 Agents fragen, Antworten vergleichen, Confidence bewerten
- **Capability Schema** — formale Beschreibung was ein Agent kann
- **Auth** — API Keys pro Agent mit HMAC-Signierung

## Wie es funktioniert

```
Consumer Agent                    Nexus                     Provider Agent
      |                            |                            |
      |-- "Ich brauche            |                            |
      |    text_analysis" -------->|                            |
      |                            |-- findet besten Agent ---->|
      |                            |-- verhandelt Konditionen ->|
      |                            |-- leitet Request weiter -->|
      |                            |<--- Antwort + Confidence --|
      |                            |-- verifiziert (optional) ->|
      |                            |-- verarbeitet Zahlung ---->|
      |<-- Ergebnis + Quellen ----|                            |
      |                            |-- aktualisiert Trust ----->|
```

## Was gerade laeuft

9 Agents in meinem lokalen Nexus-Netzwerk registriert:

- **Cortex** — AI Agent OS (persistente Agents, Multi-Agent Workflows)
- **DocBrain** — Dokumentenmanagement mit OCR + AI Chat
- **Mnemonic** — Memory-as-a-Service fuer jede AI-App
- **DeepResearch** — Autonome Web-Recherche mit Report-Generierung
- **Sentinel** — Security Scanner (SQLi, XSS, 16 Checks)
- **CostControl** — LLM API Kosten-Tracking und Budgetierung
- **SafetyProxy** — Prompt Injection Erkennung, PII-Filterung
- **LogAnalyst** — AI-gestuetzte Log-Analyse und Anomalie-Erkennung
- **Echo Provider** — Demo-Agent zum Testen

Alles Open Source. Alles in 2 Tagen gebaut.

## Warum das wichtig ist

Aktuell: Wenn Agent A die Faehigkeiten von Agent B nutzen will, muss man die Integration hardcoden. Mit Nexus:

1. Agent A sagt "Ich brauche juristische Analyse"
2. Nexus findet 3 Jura-Agents, vergleicht Trust Scores und Preise
3. Routet zum besten
4. Verifiziert die Antwort gegen einen zweiten Agent
5. Wickelt die Zahlung ab
6. Aktualisiert Trust Scores

**Kein Hardcoding. Kein Mensch dazwischen. Agents verhandeln direkt.**

So hat das Internet fuer Menschen funktioniert (DNS + HTTP + HTTPS + Payments). Nexus ist dasselbe fuer AI.

## Tech Stack

- Python + FastAPI + SQLite (keine schweren Dependencies)
- 66 Tests, alle gruen
- Laeuft lokal mit Ollama (kostenlos, keine API Keys)
- MIT-lizenziert

## Was als naechstes kommt

- Federation mit echten Remote-Instanzen
- Nexus SDK fuer andere Sprachen (TypeScript, Go)
- Agent Marketplace (Agent listen, Preise setzen, Credits verdienen)
- Formale Protokoll-Spec (RFC-aehnliches Dokument)

---

**GitHub:** https://github.com/timmeck/nexus

Fragen? Das ist ernsthaft etwas das noch nicht existiert — ich habe 15.576 Repos auf GitHub analysiert um das zu verifizieren bevor ich es gebaut habe.

Gebaut von Tim Mecklenburg | Gebaut mit Claude Code
