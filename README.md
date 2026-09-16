Here’s a revised and clearly formatted `README.md` section for your `baasha-service-api` project, including detailed **Docker usage**, how to use `COMPOSE_PROFILES`, and how to configure the `.env` file:

---

# baasha-service-api

This is a Flask-SQLAlchemy-based Python server that exposes REST APIs for Baasha Service operations. It supports managing **Ideas**, **Drafts**, **Previews**, **Voices**, and **Background Music**, and connects to a **PostgreSQL** database.

---

## 🐳 Docker Deployment

The easiest way to run the service is via Docker Compose.

### 🔑 Step 1: Authenticate to GitHub Container Registry (GHCR)

```bash
echo $CR_PAT | docker login ghcr.io -u USERNAME --password-stdin
```

Where `CR_PAT` is a [GitHub Personal Access Token](https://github.com/settings/tokens) with appropriate `read:packages` permissions.

---

### 📄 Step 2: Define a `.env` File

In the root directory, create a `.env` file to provide necessary configuration. For example:

```env
REGION=us-east
ID=myapp

# Linode Object Storage credentials
LINODE_ACCESS_KEY=your-access-key
LINODE_SECRET_KEY=your-secret-key
LINODE_BUCKET_NAME=baasha-logs
LINODE_REGION=us-east-1

# New Relic
NEW_RELIC_LICENSE_KEY=your-nr-key
```

> `REGION` and `ID` are used to construct the public hostname in Caddy:
> `https://${REGION}-${ID}.api.pataka.app` or `https://${REGION}-${ID}.api-stage.pataka.app`

---

### 📦 Step 3: Pull the Latest Image

```bash
docker pull ghcr.io/baashalive/service-api:latest
```

---

### 🚀 Step 4: Start Services

Start production (default):

```bash
docker compose --profile prod up -d
```

Or start staging:

```bash
COMPOSE_PROFILES=stage docker compose up -d
```

---

### 🔍 Verifying Services

* Caddy serves the service over **ports 80 and 443** using automatic reverse proxy and load balancing.
* The actual Flask server runs on **port 5000**, internally exposed to Caddy.
* Logs are written to `./logs` and consumed by **fluent-bit** for forwarding to New Relic and Linode Object Storage.

---

## 📚 API Overview

(You can later auto-generate this section using Swagger/OpenAPI)

* **Ideas**
* **Drafts**
* **Voices**
* **Background Music**

---

## 🧪 Local Setup (Deprecated)

This is unmaintained, but can be used for local development.

### Set Up Local Database

```bash
./scripts/create_network.sh
./scripts/setup_local_db.sh
./scripts/run_adminer.sh  # optional admin panel
```

### Install Baasha Pipeline (for Draft Rendering)

```bash
python -m venv venv
source venv/bin/activate

./scripts/get_baasha_pipeline.sh
pip install baasha_pipeline.tar.gz
pip install -r requirements.txt
```

### Run Flask Server (Locally)

```bash
python app.py
```

---
