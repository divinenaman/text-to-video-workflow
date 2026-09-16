# Baasha: Multi-Modal Text-to-Video Production Engine

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.0+-black?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Google ADK](https://img.shields.io/badge/Google%20ADK-Gemini%203%20Flash-4285F4?style=flat-square&logo=google&logoColor=white)](https://ai.google.dev/)
[![FastMCP](https://img.shields.io/badge/FastMCP-SSE-8A2BE2?style=flat-square)](https://modelcontextprotocol.io/)
[![Remotion](https://img.shields.io/badge/Renderer-Remotion%20(React)-0B84F3?style=flat-square&logo=react&logoColor=white)](https://www.remotion.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-336791?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Valkey](https://img.shields.io/badge/Valkey-Distributed%20Locking-D82C20?style=flat-square&logo=redis&logoColor=white)](https://valkey.io/)
[![Docker](https://img.shields.io/badge/Docker-Caddy%20Gateway-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)

An end-to-end production engine and AI Creative Director for serialized short-form video. The system couples multi-modal generation (Gemini, ElevenLabs, image diffusion) with a declarative JSON video DSL rendered via a headless Remotion engine, maintaining character continuity across episodes and enabling non-destructive, agentic editing.

---

## Video Demos

### 1. Studio Walkthrough & Architecture Demo
A complete 15-minute walkthrough of the production board, screenplay blueprinting, character reference locking, and stage transitions:

[![Watch Studio Walkthrough on YouTube](docs/walkthrough_preview.jpg)](https://youtu.be/7JbBc1PEM34)

> **Link**: [Watch Full Studio Walkthrough on YouTube (15 mins)](https://youtu.be/7JbBc1PEM34)

---

### 2. Generated Output Sample
Cinematic short generated entirely through the pipeline (Interstellar docking scene recreation):

[![Watch Sample Output on YouTube Shorts](https://img.youtube.com/vi/SSpNvivciqU/hqdefault.jpg)](https://www.youtube.com/shorts/SSpNvivciqU)

> **Link**: [Watch Generated Output on YouTube Shorts](https://www.youtube.com/shorts/SSpNvivciqU)

---

## Core Problem & Technical Approach

| Challenge | Technical Solution |
| :--- | :--- |
| **Character Drift Across Shots** | **Continuity Protocol**: Extracts reference portrait anchors and queries `pgvector` memory across episodes to lock facial geometry and aesthetic. |
| **Un-editable Black-Box Video** | **Declarative Video DSL**: Serializes video into a JSON AST rendered by Remotion. The AI agent edits the AST directly without re-rendering unaffected assets. |
| **Directorial & Pacing Control** | **16-Panel Locked Grid**: Maps scene shot lists to rigid canvas templates (`grid.png`) to lock horizon lines and staging prior to video assembly. |
| **Pipeline Race Conditions** | **Valkey Session Locks**: Deterministic 5-minute distributed locks per draft stage to prevent parallel GPU/render overwrite conflicts. |

---

## System Architecture

```mermaid
flowchart TD
    subgraph ClientDirection ["Client and Direction"]
        User["Creator / Director"]
        Agent["Google ADK Creative Director (Gemini 3 Flash)"]
        User --- Agent
    end

    subgraph AgenticTooling ["Agentic Tooling"]
        MCP["FastMCP SSE Server (Port 8000)"]
        Agent --- MCP
    end

    subgraph CoreEngine ["Core Engine"]
        API["Flask REST API (Port 5000)"]
        MCP --> API
        Valkey[("Valkey / Redis (Distributed Session Locks)")]
        DB[("PostgreSQL + pgvector (Ideas, Drafts, Bibles)")]
        API --- Valkey
        API --- DB
    end

    subgraph Pipeline ["5-Stage Production Pipeline"]
        S0["Stage 0: Screenplay Blueprint"]
        S1["Stage 1: Soundscape and ElevenLabs TTS"]
        S2["Stage 2: Aesthetic Sref and Visual Prompts"]
        S3["Stage 3: 16-Panel Grid Storyboard Audit"]
        S4["Stage 4: Remotion DSL Compilation and MP4 Render"]
        S0 --> S1 --> S2 --> S3 --> S4
    end

    API --> S0
    S4 --> Output["Final Rendered MP4 and Webhook Callback"]

    subgraph Observability ["Observability"]
        FB["Fluent-Bit Log Shipper"]
        NR["New Relic APM"]
        S3Storage["Linode S3 Storage"]
        API -.-> FB
        FB --> NR
        FB --> S3Storage
    end
```

---

## Key Engineering Highlights

### 1. Declarative Video DSL and Remotion React Renderer
Instead of generating monolithic, un-editable video files, the pipeline compiles video compositions into a JSON Abstract Syntax Tree (AST):
* **Component Primitives**: Supports `parallel` (Z-Stack / V-Stack), `transition` (emerge, slide), `img` (with wobble and zoom keyframes), `audio`, and `subtitle_text`.
* **Phoneme Alignment**: Subtitles map to sub-second audio `timepoints` emitted by the TTS engine.
* **Non-Destructive AI Editing**: The LLM agent inspects and modifies the JSON AST directly (e.g. adjusting font weights, transition durations, or audio ducking) without triggering expensive image/audio re-generation.
* **Headless Chromium Execution**: A custom `parseConfig` compiler dynamically resolves JSON nodes to React component closures rendered via Remotion (`@remotion/renderer`) on Docker/Lambda.

### 2. Agentic Creative Director (Google ADK + FastMCP)
Implemented in `agents/baasha_director/agent.py` and `mcp_server.py`:
* Built on Google ADK with `gemini-3-flash-preview` communicating via Server-Sent Events (SSE) over FastMCP.
* Exposes 15+ specialized video tools for screenplay blueprinting, moodboard generation, stage advancement, and asset auditing.
* Implements mandatory human-in-the-loop checkpoints before advancing pipeline stages.

### 3. Episodic Continuity & Lineage Protocol
* **Character Bibles**: Extracts facial structural anchors (eye shape, nose profile, jawline silhouette) to constrain diffusion prompts.
* **Vector Memory**: Uses `pgvector` embeddings to identify recurring characters and visual styles across multi-episode series.

### 4. Distributed State Machine & Locking
* Multi-minute asset generation is synchronized via Valkey (Redis-compatible key-value store).
* Optimistic distributed locks with automatic 5-minute timeouts prevent parallel write collisions while drafts progress through stages 0 to 4.

### 5. Production Observability & Infrastructure
* **Gateway**: Caddy reverse proxy providing automatic TLS termination and dynamic domain routing.
* **Telemetry**: Fluent-Bit daemon streaming structured application logs and stack traces to New Relic APM and Linode Object Storage (S3-compatible).
* **Async Callbacks**: Long-running video renders trigger authenticated webhook notifications upon completion.

---

## Technology Stack

* **Backend**: Python 3.11, Flask, Flask-RESTful, SQLAlchemy, Pydantic
* **AI & Agentic Systems**: Google Agent Development Kit (ADK), Gemini 3 Flash, FastMCP
* **Video Rendering**: Remotion 4.x, React, Node.js, FFmpeg, ImageMagick
* **Data & Cache**: PostgreSQL, `pgvector`, Valkey / Redis
* **Audio & Multi-Modal**: ElevenLabs, Fal.ai Diffusion APIs, NLTK, TextBlob
* **DevOps & Observability**: Docker Compose, Caddy, Fluent-Bit, New Relic, Linode S3

---

## Documentation & Quick Start

* [Deployment & Local Setup Guide (DEPLOYMENT.md)](DEPLOYMENT.md)
* [REST API Documentation (API_DOC.md)](API_DOC.md)
* [Valkey Setup & Docker Configuration (VALKEY.md)](VALKEY.md)

### Running Services
```bash
# Start backend and gateway (Docker)
docker compose --profile prod up -d

# Start FastMCP server (Port 8000)
python mcp_server.py

# Start Creative Director Agent
python -m agents.baasha_director.agent
```
