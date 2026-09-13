FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY requirements.txt pyproject.toml ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY README.md LICENSE ./
RUN python -m pip install --no-cache-dir --no-deps . \
    && useradd --create-home --uid 10001 guardian

USER guardian
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8080')+'/health', timeout=3).read()"

CMD ["python", "-m", "ambient_guardian.official_server"]
