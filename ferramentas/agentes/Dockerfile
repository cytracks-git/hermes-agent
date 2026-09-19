# Lab da prova do card t_37dc47cd (claim_lock nao e identidade de autoria).
#
# python:3.13-slim + pytest e o suficiente: `hermes_cli.kanban_db` so usa
# stdlib (medido: import limpo nesta imagem sem instalar as 35 deps do
# pyproject). Imagem minima para que a bateria rode NAO-ROOT em segundos.
#
#   docker build -t atlas-claimlock-lab:1 ferramentas/agentes/
#   ferramentas/agentes/prova-claim-lock-nao-e-identidade.sh
FROM python:3.13-slim
RUN pip install --no-cache-dir pytest==8.3.4
