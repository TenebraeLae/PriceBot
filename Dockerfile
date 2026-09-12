FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml ./
COPY pricebot ./pricebot
COPY content ./content
COPY scripts ./scripts

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir .

EXPOSE 8080
CMD ["uvicorn", "pricebot.web.main:app", "--host", "0.0.0.0", "--port", "8080"]
