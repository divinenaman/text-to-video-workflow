#!/bin/bash

PIPELINE_REPO="https://api.github.com/repos/BaashaLive/baasha-pipeline"
GIT_TOKEN=$(awk -F "=" '/GIT_TOKEN/ {print $2}' ../config.ini | tr -d ' ')
url=$(curl --silent -H "Authorization: Bearer $GIT_TOKEN" "$PIPELINE_REPO"/releases/latest 2>&1 | grep "$PIPELINE_REPO"/releases/assets/ | cut -d '"' -f4)
curl -vLj -H "Authorization: Bearer $GIT_TOKEN" -H 'Accept: application/octet-stream' "$url" --output baasha_pipeline.tar.gz
