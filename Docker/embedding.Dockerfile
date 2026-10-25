FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HF_HOME=/models HF_HUB_DISABLE_XET=1 TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
COPY Docker/embedding-requirements.txt /tmp/embedding-requirements.txt
COPY --chown=10001:10001 embedding-server/app ./app
COPY --chown=10001:10001 embedding-server/routers ./routers
COPY --chown=10001:10001 Docker/embedding-entrypoint.py /app/embedding-entrypoint.py
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=secret,id=ca_bundle \
    if [ -s /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    pip install --index-url https://download.pytorch.org/whl/cu129 'torch==2.13.0+cu129' && \
    pip install -r /tmp/embedding-requirements.txt && pip check && \
    mkdir /models && chown 10001:10001 /models
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --start-period=600s --retries=5 \
  CMD python -c "import json,urllib.request; r=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=4)); assert r['status']=='ok' and r['dim']==1024"
ENTRYPOINT ["python", "/app/embedding-entrypoint.py"]
