FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/New_York

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root runtime; data/ must be writable for state, blotter and rotation.
RUN useradd --create-home --shell /bin/bash trader \
    && mkdir -p /app/data \
    && chown -R trader:trader /app
USER trader

# Fails if the bot stops refreshing its state file.
HEALTHCHECK --interval=5m --timeout=20s --start-period=2m --retries=3 \
    CMD python -c "import json,sys,time; \
d=json.load(open('data/state.json')); \
sys.exit(0 if time.time()-__import__('datetime').datetime.fromisoformat(d['saved_at']).timestamp() < 1800 else 1)"

CMD ["python", "main.py"]
