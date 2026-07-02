FROM python:3.12-slim

WORKDIR /app

COPY bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/
COPY main.py .

# -u keeps logs unbuffered so `docker compose logs` is live.
CMD ["python", "-u", "main.py"]
