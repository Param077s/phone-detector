# Vigil — cloud image (Render, Railway, Fly, any Docker host)
FROM python:3.11-slim

# OpenCV runtime libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Small instances: light model, no tiling. Override per-deploy as needed.
ENV MODEL_NAME=yolo11n.pt \
    TILING=false \
    IMG_SIZE=640 \
    VIGIL_NO_DEFAULT_CAMERA=1

EXPOSE 8000
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}
