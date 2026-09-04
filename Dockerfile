FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/base.txt requirements/base.txt
COPY requirements/backend.txt requirements/backend.txt

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r requirements/backend.txt \
    && python -m pip install paddlepaddle==3.2.2 paddleocr==3.7.0

COPY . .
RUN mkdir -p /app/var/files

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
