#!/bin/bash
set -e

IMAGE="warship-v2"
CONTAINER="warship-v2"

echo "Stopping container..."
docker stop $CONTAINER 2>/dev/null || true

echo "Removing container..."
docker rm $CONTAINER 2>/dev/null || true

echo "Removing image..."
docker rmi $IMAGE 2>/dev/null || true

echo "Building image..."
docker build -t $IMAGE .

echo "Starting container..."
docker run -d --network host --name $CONTAINER --env-file .env $IMAGE

echo "Done. Checking health..."
sleep 2
curl -s http://localhost:8088/health
