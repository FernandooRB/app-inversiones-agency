FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 SIG_DATA_DIR=/var/data
WORKDIR /app
COPY requirements.txt constraints-tested.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 sig \
    && mkdir -p /var/data /app/.streamlit \
    && chown -R sig:sig /app /var/data
# Explicit public-code inputs; original statements and local evidence never enter the image.
COPY --chown=sig:sig *.py ./
COPY --chown=sig:sig scripts/ ./scripts/
COPY --chown=sig:sig data/ ./data/
COPY --chown=sig:sig docs/ ./docs/
COPY --chown=sig:sig .streamlit/config.toml ./.streamlit/config.toml
USER sig
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8501')+'/_stcore/health',timeout=4)"
CMD ["python", "deployment_runtime.py"]
