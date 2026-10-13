#!/bin/bash

CONTAINER_NAME="baasha-s3"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(docker ps -q -f status=running -f name=^/${CONTAINER_NAME}$)" ]; then
    echo "Local S3 container '${CONTAINER_NAME}' is already running."
    echo "Endpoint: http://localhost:9000"
elif [ "$(docker ps -aq -f name=^/${CONTAINER_NAME}$)" ]; then
    echo "Starting existing container '${CONTAINER_NAME}'..."
    docker start "${CONTAINER_NAME}"
    echo "Waiting for container readiness..."
    sleep 3
    echo "Local S3 container started on http://localhost:9000"
else
    echo "Container '${CONTAINER_NAME}' not found. Running setup..."
    bash "${DIR}/setup_local_s3.sh"
fi
