# api/Dockerfile — FastAPI-сервис (СЛОЙ 4). Собирается из корня репозитория:
#   docker compose build api   (см. docker-compose.yml: context: ., dockerfile: api/Dockerfile)
#
# Тяжёлые ML-зависимости (catboost/plotly/pdfplumber) сюда намеренно не
# ставятся — API их не импортирует (проверено: ни один api/**.py не
# импортирует siar/ml/parsers). Прогон модели и SIAR-отчётов — на хосте,
# см. DEPLOY.md.
FROM python:3.11-slim

WORKDIR /app

COPY api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY api ./api

# .env НЕ копируется в образ (секреты — только через docker-compose environment).

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
