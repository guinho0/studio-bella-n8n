FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Sao_Paulo

WORKDIR /app

# Dependências primeiro: esta camada só é refeita quando o requirements.txt muda.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agente/ agente/
COPY api/ api/
COPY negocio/ negocio/

# Usuário sem privilégios; dados/ é onde o volume do SQLite é montado.
RUN useradd --create-home --uid 1000 app && mkdir -p /app/dados && chown app:app /app/dados
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)"

CMD ["uvicorn", "api.main:criar_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
