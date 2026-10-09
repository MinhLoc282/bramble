
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV SYNC_STATE_DIR=/app/state
ENV SYNC_LOG_DIR=/app/logs

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scraper/ ./scraper/
COPY main.py .

CMD ["python", "main.py"]