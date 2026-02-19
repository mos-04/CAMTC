FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY blockchain/ ./blockchain/
COPY consensus/ ./consensus/
COPY integration/ ./integration/
COPY gateway/ ./gateway/
COPY scripts/ ./scripts/

EXPOSE 5000
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "5000"]
