# Imagem de prova do contrato de aprovacao humana (card t_78aaa333).
#
# Existe porque o host NAO tem venv com pytest para este worktree e a instalacao
# de dependencias no host e recusada pelo scanner em modo headless. A regra 12 do
# Atlas manda provar no Docker, entao a suite roda aqui -- pelo runner canonico
# `scripts/run_tests.sh`, nunca por `pytest` cru.
#
# A base `kanban-body-t5a6:proof` ja traz pytest 8.3.4 / pytest-asyncio /
# pytest-timeout. Acrescentamos somente o que a suite do dashboard exige.
# Versoes pinadas conforme a politica de dependencias do repositorio.
FROM kanban-body-t5a6:proof

RUN pip install --no-cache-dir \
      fastapi==0.133.1 \
      starlette==0.52.1 \
      python-multipart==0.0.20 \
      uvicorn==0.35.0

# `scripts/run_tests.sh` aceita HERMES_PYTHON quando nao ha venv local; e o
# caminho previsto pelo proprio runner, nao um contorno.
ENV HERMES_PYTHON=/usr/local/bin/python3 \
    TZ=UTC \
    LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1
