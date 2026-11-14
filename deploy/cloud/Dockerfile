FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app
COPY requirements-cloud.txt requirements-cloud.lock ./
RUN pip install --no-cache-dir -r requirements-cloud.lock && useradd --uid 10001 --create-home atlas
COPY src/ambient_guardian ./src/ambient_guardian
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=2).read()"
CMD ["python","-m","ambient_guardian.cloud_core"]
