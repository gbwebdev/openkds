FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY openkds/ ./openkds/
RUN pip install --no-cache-dir .

ENV OPENKDS_DATA_DIR=/data
VOLUME ["/data"]

EXPOSE 8000

CMD ["openkds"]
