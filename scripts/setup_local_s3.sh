#!/bin/bash
set -e

CONTAINER_NAME="baasha-s3"
IMAGE_NAME="adobe/s3mock:3.11.0"
PORT_HTTP="9000"
PORT_HTTP_ALT="9090"
PORT_HTTPS="9191"
BUCKETS="baasha-assets,baasha-bgm"

echo "=========================================="
echo "  Setting up Local S3 (S3Mock) Container  "
echo "=========================================="

# 1. Ensure shared docker network exists
if ! docker network inspect baasha >/dev/null 2>&1; then
    echo "Creating Docker network 'baasha'..."
    docker network create baasha
fi

# 2. Check if Docker image is already available locally, pull if needed
if ! docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1; then
    echo "Pulling Docker image ${IMAGE_NAME}..."
    docker pull "${IMAGE_NAME}"
fi

# 3. Clean up any existing container with the same name
if [ "$(docker ps -aq -f name=^/${CONTAINER_NAME}$)" ]; then
    echo "Stopping and removing existing container '${CONTAINER_NAME}'..."
    docker rm -f "${CONTAINER_NAME}" >/dev/null
fi

# 4. Start local S3 container
echo "Starting '${CONTAINER_NAME}'..."
docker run -d \
    --name "${CONTAINER_NAME}" \
    --network baasha \
    -p "${PORT_HTTP}:9090" \
    -p "${PORT_HTTP_ALT}:9090" \
    -p "${PORT_HTTPS}:9191" \
    -e initialBuckets="${BUCKETS}" \
    -v baasha_s3_data:/tmp/s3mockFileStore \
    --restart unless-stopped \
    "${IMAGE_NAME}"

# 5. Wait for readiness
echo "Waiting for local S3 to become ready..."
MAX_ATTEMPTS=20
COUNT=0
READY=0
while [ $COUNT -lt $MAX_ATTEMPTS ]; do
    if curl -s "http://localhost:${PORT_HTTP}/baasha-assets" >/dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 1
    COUNT=$((COUNT + 1))
done

if [ $READY -eq 1 ]; then
    echo "Local S3 container is up and running!"
    echo "  - S3 API / HTTP Endpoint : http://localhost:${PORT_HTTP}"
    echo "  - Alt HTTP Port          : http://localhost:${PORT_HTTP_ALT}"
    echo "  - Initial Buckets        : ${BUCKETS}"
else
    echo "Warning: S3 container started, but readiness check timed out. Check with: docker logs ${CONTAINER_NAME}"
fi
