#!/bin/bash

echo $GITHUB_TOKEN | docker login ghcr.io -u divinenaman --password-stdin

sh ./scripts/setup_local_db.sh

docker-compose up
