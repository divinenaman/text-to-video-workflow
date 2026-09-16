#!/bin/bash

docker pull postgres:13.12-bookworm

CONTAINER_NAME='baashadb'

CID=$(docker ps -q -f status=running -f name=^/${CONTAINER_NAME}$)
if [ ! "${CID}" ]; then
  echo "Container $CONTAINER_NAME does not exist. Starting..."
  docker run --name ${CONTAINER_NAME} -p 5001:5432 -e POSTGRES_USER=baasha -e POSTGRES_PASSWORD=baasha -e POSTGRES_DB=${CONTAINER_NAME} -d postgres
else
  echo "existing container running"
fi
unset CID

# echo -e "[DATABASE]\nENGINE = postgresql\nPORT = 5001\nHOST = localhost\nUSER = baasha\nPASSWD = baasha\nDATABASE = baashadb" > config.local.ini
