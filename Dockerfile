# ==========================================================
# UPGRADED DOCKERFILE FOR PDF BANK STATEMENT OCR SUPPORT
# Adds:
# ✅ poppler-utils (pdf2image fix)
# ✅ tesseract-ocr (OCR reading)
# ✅ cleaner optimized image
# ==========================================================

# ============================
# Base stage
# ============================
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app


# ============================
# Builder stage
# ============================
FROM base AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    poppler-utils \
    tesseract-ocr \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .

RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt


# ============================
# Development stage
# ============================
FROM base AS development

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    poppler-utils \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN groupadd -r app && useradd -r -g app -d /app -s /usr/sbin/nologin app

COPY . .

RUN chown -R app:app /app

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


# ============================
# Production stage
# ============================
FROM base AS production

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    poppler-utils \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN groupadd -r -g 1000 app \
    && useradd -r -u 1000 -g app -d /app -s /usr/sbin/nologin app

COPY . .

RUN chmod +x scripts/start.sh \
    && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=40s \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["scripts/start.sh"]