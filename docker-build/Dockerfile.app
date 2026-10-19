FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    default-libmysqlclient-dev \
    git \
    libldap2-dev \
    libpq-dev \
    libsasl2-2 \
    libsasl2-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt \
    && pip install --no-cache-dir gunicorn

COPY backend /app/backend

RUN chmod a+x /app/backend/docker-entrypoint.sh

WORKDIR /app/backend

ENTRYPOINT ["/app/backend/docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "devicevault.wsgi:application"]
