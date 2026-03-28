FROM python:3.11-slim

LABEL maintainer="RobloxOS Project"
LABEL description="RobloxOS Web Control Panel"

WORKDIR /app

# Zainstaluj zależności systemowe (minimalne)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Kopiuj i zainstaluj zależności Pythona
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiuj pliki aplikacji
COPY app.py mock_data.py ./
COPY templates/ templates/
COPY static/ static/ 2>/dev/null || true

# Stwórz katalog na dane (config.json, logi)
# Montuj jako wolumen: -v ./data:/app/data
RUN mkdir -p data/logs

# Zmienna środowiskowa wykrywa Replit/demo mode
ENV REPLIT_MODE=true
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# Healthcheck – Replit i Docker sprawdzają czy serwer odpowiada
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/login')" \
    || exit 1

CMD ["python3", "app.py"]
