# Deployment & Local Setup Guide

This guide covers everything required to deploy the **Baasha Text-to-Video Production Engine** in production using Docker Compose, Caddy, and Valkey, or run it locally for active development.

---

## Table of Contents
- [🐳 Production Deployment (Docker Compose)](#-production-deployment-docker-compose)
  - [1. Authenticate to GitHub Container Registry (GHCR)](#1-authenticate-to-github-container-registry-ghcr)
  - [2. Environment Configuration (.env)](#2-environment-configuration-env)
  - [3. Pull Image & Run Services](#3-pull-image--run-services)
  - [4. Valkey (Redis) Session Store](#4-valkey-redis-session-store)
  - [5. Verification & Observability](#5-verification--observability)
- [💻 Local Development Setup](#-local-development-setup)
  - [1. Prerequisites](#1-prerequisites)
  - [2. Setup Local PostgreSQL Database](#2-setup-local-postgresql-database)
  - [3. Python Environment & Dependencies](#3-python-environment--dependencies)
  - [4. Launch Valkey & Database Migrations](#4-launch-valkey--database-migrations)
  - [5. Run Development Servers](#5-run-development-servers)
- [🤖 Running the Agentic Creative Director & MCP Server](#-running-the-agentic-creative-director--mcp-server)

---

## 🐳 Production Deployment (Docker Compose)

The production architecture runs behind **Caddy** (handling automatic reverse proxy, HTTPS certificates, and load balancing) with containerized services for the Flask REST API, Valkey state store, and Fluent-Bit log forwarder.

### 1. Authenticate to GitHub Container Registry (GHCR)

Export your GitHub Personal Access Token (PAT) with `read:packages` permissions:

```bash
echo $CR_PAT | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
```

### 2. Environment Configuration (.env)

Create a `.env` file in the root directory:

```env
# Deployment Identifiers
REGION=us-east
ID=myapp

# Linode Object Storage (S3 Compatible)
LINODE_ACCESS_KEY=your-linode-access-key
LINODE_SECRET_KEY=your-linode-secret-key
LINODE_BUCKET_NAME=baasha-logs
LINODE_REGION=us-east-1

# Observability & Monitoring
NEW_RELIC_LICENSE_KEY=your-newrelic-license-key

# Database Connection (PostgreSQL with pgvector)
DATABASE_URL=postgresql://user:password@db-host:5432/baashadb

# Valkey / Redis Session Store
VALKEY_HOST=localhost
VALKEY_PORT=6379

# AI & Multimodal Engine Keys
GEMINI_API_KEY=your-gemini-api-key
ELEVENLABS_API_KEY=your-elevenlabs-api-key
FAL_KEY=your-fal-ai-key
```

> **Note**: `REGION` and `ID` configure the dynamic Caddy routing domains:  
> `https://${REGION}-${ID}.api.pataka.app` (production) or `https://${REGION}-${ID}.api-stage.pataka.app` (staging).

### 3. Pull Image & Run Services

Pull the latest container build:

```bash
docker pull ghcr.io/baashalive/service-api:latest
```

**Start Production Stack:**
```bash
docker compose --profile prod up -d
```

**Start Staging Stack:**
```bash
COMPOSE_PROFILES=stage docker compose up -d
```

### 4. Valkey (Redis) Session Store

Valkey handles distributed draft locking (preventing race conditions during multi-stage rendering) and session persistence.

Run as a standalone container:
```bash
docker run -d \
  --name baasha-valkey \
  -p 6379:6379 \
  valkey/valkey:latest
```

Or ensure it is declared in your `docker-compose.yml`:
```yaml
services:
  valkey:
    image: valkey/valkey:latest
    container_name: valkey
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - valkey_data:/data
    networks:
      - caddy
    command: ["valkey-server", "--save", "60", "1", "--loglevel", "warning"]

volumes:
  valkey_data:
```

Test connection:
```bash
docker exec -it baasha-valkey valkey-cli ping
# Output: PONG
```

### 5. Verification & Observability

- **Caddy Gateway**: Serves traffic over **ports 80 and 443** with automatic SSL termination.
- **Flask API Core**: Runs internally on **port 5000**, exposed securely to Caddy.
- **Fluent-Bit Logging**: Streams output from `./logs` and `/tmp/logs` to **New Relic APM** and **Linode Object Storage**.

Check logs:
```bash
docker compose logs -f
```

---

## 💻 Local Development Setup

For local iteration, testing endpoints, and experimenting with prompt engines:

### 1. Prerequisites
- Python 3.10 or 3.11
- Docker & Docker Compose
- FFmpeg & ImageMagick (`sudo apt install ffmpeg imagemagick libsm6 libxext6`)

### 2. Setup Local PostgreSQL Database

Initialize the Docker network and local PostgreSQL instance (with pgvector support):

```bash
# Create shared docker bridge network
./scripts/create_network.sh

# Spin up local PostgreSQL container
./scripts/setup_local_db.sh

# (Optional) Launch Adminer web UI for DB inspection (accessible on port 8080)
./scripts/run_adminer.sh
```

### 3. Python Environment & Dependencies

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install pipeline dependencies & core packages
pip install --upgrade pip
pip install -r requirements.txt

# Download NLP models and corpora
python -m textblob.download_corpora
python nltk_download.py
```

### 4. Launch Valkey & Database Migrations

Run Valkey in Docker:
```bash
docker run -d --name baasha-valkey -p 6379:6379 valkey/valkey:latest
```

Run schema migrations if needed:
```bash
python db_migrations.txt  # Or apply SQL schema definitions
```

### 5. Run Development Servers

Start the local Flask API:
```bash
python app.py
```
API server runs on `http://127.0.0.1:5000`.

---

## 🤖 Running the Agentic Creative Director & MCP Server

The system includes a Google ADK-powered AI Creative Director that interfaces with the pipeline via the Model Context Protocol (MCP).

### 1. Launch FastMCP Server
```bash
python mcp_server.py
```
This exposes the SSE (Server-Sent Events) interface on `http://localhost:8000/sse`.

### 2. Run Google ADK Agent
```bash
python -m agents.baasha_director.agent
```
The agent connects over SSE to orchestrate screenplay blueprints, trigger storyboard stages, review generated frames, and perform surgical refinements.

---

[⬅️ Back to Main README](README.md) | [📖 View API Documentation](API_DOC.md)
