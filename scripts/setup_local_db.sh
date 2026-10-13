#!/bin/bash

docker pull postgres:13.12-bookworm

CONTAINER_NAME='baashadb'

if [ "$(docker ps -q -f status=running -f name=^/${CONTAINER_NAME}$)" ]; then
  echo "Existing container ${CONTAINER_NAME} is already running"
elif (echo > /dev/tcp/localhost/5001) 2>/dev/null; then
  echo "PostgreSQL is already active and listening on port 5001"
elif [ "$(docker ps -aq -f name=^/${CONTAINER_NAME}$)" ]; then
  echo "Starting existing container ${CONTAINER_NAME}..."
  docker start "${CONTAINER_NAME}"
else
  echo "Container ${CONTAINER_NAME} does not exist. Starting..."
  docker run --name ${CONTAINER_NAME} -p 5001:5432 -e POSTGRES_USER=baasha -e POSTGRES_PASSWORD=baasha -e POSTGRES_DB=${CONTAINER_NAME} -d postgres
fi

# echo -e "[DATABASE]\nENGINE = postgresql\nPORT = 5001\nHOST = localhost\nUSER = baasha\nPASSWD = baasha\nDATABASE = baashadb" > config.local.ini
