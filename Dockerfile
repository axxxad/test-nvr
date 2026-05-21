# Stage 1: build Tailwind + DaisyUI CSS
FROM node:22-alpine AS css-builder
WORKDIR /build
COPY package.json package-lock.json* ./
COPY static ./static
COPY app/templates ./app/templates
RUN npm ci 2>/dev/null || npm install
RUN npm run build:css

# Stage 2: Python runtime
FROM python:3.12-slim
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY --from=css-builder /build/app/static/css ./app/static/css

ENV DATABASE_URL=sqlite:////data/nvr.db

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
