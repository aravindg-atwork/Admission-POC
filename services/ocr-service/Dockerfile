FROM python:3.12-slim

WORKDIR /app

# Install system deps: pypdfium2 needs libjpeg, libpng, etc.
# Also install poppler-utils for pdf2image fallback if needed
RUN apt-get update && apt-get install -y \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libwebp-dev \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default port
ENV OCR_PORT=8002
ENV OCR_USE_GPU=0
ENV OCR_MODEL=baidu/Unlimited-OCR

# Volume for API keys
VOLUME /data

EXPOSE 8002

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${OCR_PORT}"]

