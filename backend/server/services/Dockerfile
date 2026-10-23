# Общий образ для Python-сервисов. Контекст сборки — backend/server:
#   docker build -f backend/server/services/Dockerfile --build-arg SERVICE=auth backend/server
FROM python:3.12-slim

ARG SERVICE
ARG APT_PACKAGES=""

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Europe/Moscow

RUN if [ -n "$APT_PACKAGES" ]; then \
      apt-get update && apt-get install -y --no-install-recommends $APT_PACKAGES && rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /app

# Слои от редко к часто меняющимся: тяжёлые зависимости сервиса → зависимости common → код common → код сервиса
COPY services/${SERVICE}/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY libs/common/pyproject.toml /tmp/common/pyproject.toml
RUN mkdir -p /tmp/common/common && touch /tmp/common/common/__init__.py && pip install /tmp/common && rm -rf /tmp/common

COPY libs/common /tmp/common
RUN pip install --no-deps --force-reinstall /tmp/common && rm -rf /tmp/common

COPY infra/cameras.yml /app/infra/cameras.yml
COPY services/${SERVICE}/ /app/

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
