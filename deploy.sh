#!/bin/bash
set -euo pipefail

IMAGE="warship-v2"
CONTAINER="warship-v2"
ASSETS_DIR="$(pwd)/static/assets"

echo "Stopping container..."
docker stop $CONTAINER 2>/dev/null || true

echo "Removing container..."
docker rm $CONTAINER 2>/dev/null || true

echo "Removing image..."
docker rmi $IMAGE 2>/dev/null || true

echo "Building image..."
docker build -t $IMAGE .

echo "Starting container..."
docker run -d --network host \
	--name $CONTAINER \
	--env-file .env \
	-v "$ASSETS_DIR:/app/static/assets:ro" \
	$IMAGE

echo "Done. Checking health..."
for i in {1..20}; do
	if curl -fs http://localhost:8088/health >/dev/null 2>&1; then
		echo "Healthy: http://localhost:8088/health"
		exit 0
	fi
	if (( i == 1 || i % 5 == 0 )); then
		echo "Waiting for app startup... (${i}/20)"
	fi
	sleep 1
done

echo "Health check failed. Recent container logs:"
docker logs --tail 80 "$CONTAINER" || true
exit 1
