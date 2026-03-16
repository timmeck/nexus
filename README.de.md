# Nexus

**AI-zu-AI-Protokollschicht** | Discovery | Trust | Protokoll | Routing

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/license-MIT-gold.svg)](LICENSE)

---

Nexus ist eine standardisierte Protokollschicht, die es autonomen KI-Agenten ermöglicht, einander zu **entdecken**, miteinander zu **verhandeln** und standardisiert zu **kommunizieren**. Es liefert die Infrastruktur, die isolierte Agenten in ein interoperables Netzwerk verwandelt.

Vergleichbar mit DNS + HTTP + einem Reputationssystem -- aber für KI-Agenten.

## Das Problem

Jeder KI-Agent spricht seine eigene Sprache. Agent A kann Agent B nicht finden, weiss nicht, was B anbietet, hat keinen Grund, Bs Ergebnissen zu vertrauen, und keinen standardisierten Weg, eine Anfrage zu senden. Nexus löst alle vier Probleme.

## Architektur

```
┌─────────────────────────────────────────────────────────────┐
│                        NEXUS CORE                           │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐   │
│  │  Discovery   │  │    Trust    │  │     Protokoll    │   │
│  │   Schicht    │  │   Schicht   │  │     Schicht      │   │
│  │             │  │             │  │                  │   │
│  │ • Registry   │  │ • Scoring   │  │ • NexusRequest   │   │
│  │ • Suche      │  │ • Tracking  │  │ • NexusResponse  │   │
│  │ • Heartbeat  │  │ • Reports   │  │ • Negotiation    │   │
│  └──────┬──────┘  └──────┬──────┘  └────────┬─────────┘   │
│         │                │                   │              │
│         └────────────────┼───────────────────┘              │
│                          │                                  │
│                  ┌───────┴───────┐                          │
│                  │    Routing    │                          │
│                  │    Schicht    │                          │
│                  │               │                          │
│                  │ • best        │                          │
│                  │ • cheapest    │                          │
│                  │ • fastest     │                          │
│                  │ • trusted     │                          │
│                  └───────────────┘                          │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │            WebSocket-Echtzeitbus                     │   │
│  └─────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────┘
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
        ┌───────┐     ┌───────┐     ┌───────┐
        │Agent A│     │Agent B│     │Agent C│
        └───────┘     └───────┘     └───────┘
```

### Die vier Schichten

| Schicht | Aufgabe | Kernfunktion |
|---------|---------|--------------|
| **Discovery** | Agenten-Registry und Fähigkeitensuche | Agenten registrieren sich, andere finden sie nach Fähigkeit |
| **Trust** | Reputationsbewertung und Interaktionsverfolgung | Jede Interaktion aktualisiert Trust-Scores automatisch |
| **Protokoll** | Standardisierte Request/Response-Nachrichten | `NexusRequest` rein, `NexusResponse` raus -- immer |
| **Routing** | Intelligente Agenten-Zuordnung | Vier Strategien: best, cheapest, fastest, trusted |

## Schnellstart

```bash
# Klonen und installieren
git clone https://github.com/timmeck/nexus.git
cd nexus
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Nexus starten
python run.py
```

Nexus läuft jetzt unter `http://localhost:9500`. Das Dashboard öffnen oder `/docs` für die interaktive API aufrufen.

![Nexus Dashboard](docs/dashboard.png)

### Ersten Agenten registrieren

```bash
curl -X POST http://localhost:9500/api/registry/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "mein-agent",
    "endpoint": "http://localhost:8000",
    "capabilities": [
      {
        "name": "zusammenfassung",
        "description": "Fasst Textdokumente zusammen",
        "languages": ["de", "en"]
      }
    ]
  }'
```

### Anfrage durch Nexus senden

```bash
curl -X POST http://localhost:9500/api/protocol/request \
  -H "Content-Type: application/json" \
  -d '{
    "from_agent": "consumer-001",
    "query": "Fasse die aktuelle Forschung zu LLM-Agenten zusammen",
    "capability": "zusammenfassung"
  }'
```

Nexus findet den am besten passenden Agenten, leitet die Anfrage weiter, verfolgt die Interaktion und aktualisiert die Trust-Scores.

## API-Referenz

### Registry

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| `POST` | `/api/registry/agents` | Neuen Agenten registrieren |
| `GET` | `/api/registry/agents` | Agenten auflisten (Filter: Status, Fähigkeit, Tag) |
| `GET` | `/api/registry/agents/{id}` | Agenten-Details abrufen |
| `PATCH` | `/api/registry/agents/{id}` | Agenten aktualisieren |
| `DELETE` | `/api/registry/agents/{id}` | Agenten abmelden |
| `POST` | `/api/registry/agents/{id}/heartbeat` | Heartbeat senden |
| `GET` | `/api/registry/discover?capability=...` | Agenten nach Fähigkeit entdecken |

### Protokoll

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| `POST` | `/api/protocol/request` | NexusRequest einreichen |
| `GET` | `/api/protocol/active` | Aktive Anfragen auflisten |

### Router

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| `POST` | `/api/router/route?strategy=best` | Passende Agenten finden ohne Ausführung |

### Trust

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| `GET` | `/api/trust/report/{agent_id}` | Trust-Bericht abrufen |
| `GET` | `/api/trust/history/{agent_id}` | Interaktionshistorie abrufen |

### System

| Methode | Endpunkt | Beschreibung |
|---------|----------|-------------|
| `GET` | `/health` | Statusprüfung |
| `GET` | `/api/stats` | Netzwerkstatistiken |
| `WS` | `/ws/agent/{agent_id}` | Echtzeit-Agent-WebSocket |
| `WS` | `/ws/dashboard` | Echtzeit-Dashboard-Updates |

## Protokollspezifikation

### NexusRequest

```json
{
  "request_id": "automatisch generierte UUID",
  "from_agent": "agent-id",
  "to_agent": "ziel-id oder null (Router entscheidet)",
  "query": "Die eigentliche Frage oder Aufgabe",
  "capability": "benötigte Fähigkeit",
  "constraints": {},
  "budget": 10.0,
  "deadline_ms": 5000,
  "verification": "none | self_reported | cross_check | deterministic",
  "language": "de",
  "context": {}
}
```

### NexusResponse

```json
{
  "response_id": "automatisch generierte UUID",
  "request_id": "zugehörige Request-ID",
  "from_agent": "antwortender-agent",
  "to_agent": "anfragender-agent",
  "status": "completed | failed | rejected | timeout",
  "answer": "Der eigentliche Antwortinhalt",
  "confidence": 0.92,
  "sources": ["quelle1", "quelle2"],
  "cost": 1.5,
  "processing_ms": 340,
  "error": null,
  "meta": {}
}
```

## Demo

Nexus wird mit Demo-Agenten ausgeliefert, die das Protokoll in Aktion zeigen:

```bash
# Terminal 1 — Nexus-Kern
python run.py

# Terminal 2 — Provider-Agent (Port 9501)
python agents/provider.py

# Terminal 3 — Consumer-Agent (Port 9502)
python agents/consumer.py

# Optional — Bestehende Agenten registrieren (Cortex, DocBrain, etc.)
python agents/register_existing.py
```

Der Provider registriert seine Fähigkeiten bei Nexus. Der Consumer entdeckt den Provider über Nexus und sendet Anfragen durch die Protokollschicht. Trust-Scores werden in Echtzeit aktualisiert.

## Docker

```bash
# Gesamtes System starten
docker compose up -d

# Logs ansehen
docker compose logs -f nexus

# Herunterfahren
docker compose down
```

Damit laufen Nexus auf Port 9500, der Demo-Provider auf 9501 und der Demo-Consumer auf 9502.

## Vergleich

| Merkmal | Nexus | Google A2A | Anthropic MCP |
|---------|-------|------------|---------------|
| Agenten-Discovery | Eingebaute Registry + Fähigkeitensuche | DNS-basiert | Nicht enthalten |
| Trust-Scoring | Automatisch, pro Interaktion | Nicht enthalten | Nicht enthalten |
| Routing-Strategien | 4 Strategien (best/cheapest/fastest/trusted) | Client-seitig | N/A |
| Nachrichtenverhandlung | Eingebaut | Nicht enthalten | Nicht enthalten |
| Echtzeit-Updates | WebSocket-Bus | Streaming | Stdio/SSE |
| Verifikation | 4 Methoden inkl. Cross-Check | Nicht enthalten | Nicht enthalten |
| Fokus | Agent-zu-Agent-Kommunikation | Agent-zu-Agent-Aufgaben | Tool-Zugriff für LLMs |

Nexus ist kein Ersatz für A2A oder MCP. Es arbeitet auf einer anderen Ebene: Während MCP Modelle mit Tools verbindet und A2A Aufgabendelegation definiert, liefert Nexus die Netzwerkinfrastruktur, die es Agenten ermöglicht, einander zu finden, Vertrauen aufzubauen und über ein standardisiertes Protokoll zu kommunizieren.

## Technologie-Stack

- **Python 3.11+** mit vollständigem async/await
- **FastAPI** für die HTTP- und WebSocket-API
- **SQLite + aiosqlite** für konfigurationsfreie Persistenz
- **Pydantic v2** für Datenvalidierung
- **httpx** für asynchrone Agent-zu-Agent-HTTP-Kommunikation

## Mitwirken

Beiträge sind willkommen. Bitte zuerst ein Issue eröffnen, um geplante Änderungen zu besprechen.

```bash
# Entwicklungsumgebung
pip install -r requirements.txt
pip install ruff

# Linting
ruff check .

# Tests
pytest -v
```

## Lizenz

[MIT](LICENSE) -- Tim Mecklenburg

---

Entwickelt von [Tim Mecklenburg](https://github.com/timmeck)
