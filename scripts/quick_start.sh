#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================================="
echo "    Baasha Video Engine - Local Environment Quick Start   "
echo "=========================================================="

# 1. Create Docker Network
sh "${DIR}/create_network.sh" >/dev/null 2>&1 || true

# 2. Local Database
echo ""
echo "[1/2] Starting Local PostgreSQL..."
bash "${DIR}/setup_local_db.sh"

# 3. Local S3 Object Storage
echo ""
echo "[2/2] Starting Local S3..."
bash "${DIR}/start_local_s3.sh"

echo ""
echo "=========================================================="
echo "  All Local Infrastructure Services Are Running! 🚀       "
echo "=========================================================="
echo "  • Local PostgreSQL : localhost:5001 (db: baashadb, user: baasha)"
echo "  • Local S3 API     : http://localhost:9000"
echo "  • S3 Buckets       : baasha-assets, baasha-bgm"
echo ""
echo "Next steps:"
echo "  1. Test S3 integration : python scripts/test_local_s3.py"
echo "  2. Start API server     : python app.py"
echo "=========================================================="
