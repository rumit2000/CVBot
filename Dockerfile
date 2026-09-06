FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HEALTH_HOST=0.0.0.0 \
    PORT=10000

WORKDIR /app

RUN groupadd --system --gid 10001 cvbot \
    && useradd --system --uid 10001 --gid cvbot \
        --home-dir /app --shell /usr/sbin/nologin cvbot

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --requirement requirements.txt

# Copy only the files used by the polling worker. Secrets and deployment
# credentials are deliberately not part of the image build context.
COPY --chown=cvbot:cvbot bot.py config.py ingestion.py polling_worker.py rag.py ./
COPY --chown=cvbot:cvbot data/ ./data/

USER cvbot

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:10000/healthz', timeout=2).read()"]

CMD ["python", "polling_worker.py"]
