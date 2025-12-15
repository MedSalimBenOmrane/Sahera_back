FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update -y && apt-get install -y dos2unix && \
    dos2unix /app/entrypoint.sh && chmod +x /app/entrypoint.sh && \
    apt-get purge -y --auto-remove dos2unix && rm -rf /var/lib/apt/lists/*

EXPOSE 80

ENTRYPOINT ["/app/entrypoint.sh"]
