FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY backend backend
COPY frontend frontend
COPY examples examples
COPY eval eval
COPY models/qwen-manifest.json models/qwen-manifest.json
RUN useradd --uid 10001 --create-home app && mkdir /app/data && chown app:app /app/data
USER app
EXPOSE 8000
CMD ["uvicorn","backend.api:app","--host","0.0.0.0","--port","8000"]
