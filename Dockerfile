ARG PYTHON_IMAGE=python:3.13-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080 \
    DATA_DIR=/data

WORKDIR /app
COPY server.py index.html VERSION /app/
RUN mkdir -p /data && chown 10001:10001 /data
USER 10001:10001

EXPOSE 8080
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8080')+'/healthz',timeout=3).read()"]
CMD ["python", "server.py"]
