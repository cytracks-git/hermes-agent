# Lab descartável; nenhum diretório HOME/credencial do operador é montado.
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pytest==8.3.4 pytest-asyncio==1.3.0 pytest-timeout==2.4.0 \
    fastapi==0.133.1 starlette==0.52.1 python-multipart==0.0.20 uvicorn==0.41.0 \
    openai==2.24.0 httpx==0.28.1 python-dotenv==1.2.2 rich==14.3.3 \
    PyYAML==6.0.3 croniter==6.0.0 psutil==7.2.2 prompt_toolkit==3.0.52 \
    requests==2.33.0 jinja2==3.1.6 tenacity==9.1.4 tiktoken==0.12.0 \
    pathspec==1.1.1 websockets==15.0.1
ENV HERMES_PYTHON=/usr/local/bin/python HOME=/tmp/launch-home TZ=UTC LANG=C.UTF-8 HERMES_TEST_FILE_RETRIES=0
WORKDIR /work
