FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools needed for asyncua's C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.12-slim

LABEL org.opencontainers.image.title="OPC UA Boiler Simulator" \
      org.opencontainers.image.description="Development OPC UA server simulating a hot-water boiler" \
      org.opencontainers.image.licenses="MIT"

# Non-root user for safer container operation
RUN groupadd --gid 1001 boiler \
 && useradd  --uid 1001 --gid boiler --no-create-home boiler

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /install /usr/local

# Copy application
COPY boiler_opcua_server.py .

# OPC UA default port
EXPOSE 4840

USER boiler

CMD ["python", "-u", "boiler_opcua_server.py"]
