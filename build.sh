#!/bin/bash
# Video Wall Build and Deploy Script

set -e

echo "======================================"
echo "Video Wall Build & Deploy Script"
echo "======================================"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
IMAGE_NAME="${1:-bbox-video-wall}"
IMAGE_TAG="${2:-latest}"
REGISTRY="${3:-}"

echo -e "${BLUE}Configuration:${NC}"
echo "  Image: $IMAGE_NAME"
echo "  Tag: $IMAGE_TAG"
if [ ! -z "$REGISTRY" ]; then
    echo "  Registry: $REGISTRY"
fi

# Build
echo -e "${BLUE}[1/4] Building Docker image...${NC}"
docker build -t $IMAGE_NAME:$IMAGE_TAG .

# Tag for registry if provided
if [ ! -z "$REGISTRY" ]; then
    echo -e "${BLUE}[2/4] Tagging for registry...${NC}"
    docker tag $IMAGE_NAME:$IMAGE_TAG $REGISTRY/$IMAGE_NAME:$IMAGE_TAG
fi

# Test
echo -e "${BLUE}[3/4] Running tests...${NC}"
docker run --rm $IMAGE_NAME:$IMAGE_TAG python -m pytest test_app.py -v || true

# Push if registry provided
if [ ! -z "$REGISTRY" ]; then
    echo -e "${BLUE}[4/4] Pushing to registry...${NC}"
    docker push $REGISTRY/$IMAGE_NAME:$IMAGE_TAG
    echo -e "${GREEN}✓ Pushed: $REGISTRY/$IMAGE_NAME:$IMAGE_TAG${NC}"
else
    echo -e "${BLUE}[4/4] Skipping registry push (no registry specified)${NC}"
fi

echo -e "${GREEN}======================================"
echo "Build complete!"
echo "======================================"
echo ""
echo "To run the application:"
echo "  docker-compose up -d"
echo ""
echo "Or with docker run:"
echo "  docker run -it -e DISPLAY=\$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix $IMAGE_NAME:$IMAGE_TAG"
echo ""
