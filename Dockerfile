# Stage 1: Build React frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/react_dashboard
COPY react_dashboard/package*.json ./
RUN npm ci
COPY react_dashboard/ ./
RUN npm run build

# Stage 2: Django + Gunicorn
FROM python:3.12-slim
WORKDIR /app

# System deps required by paramiko / cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Copy built React assets into Django's static directory
COPY --from=frontend-builder /app/react_dashboard/dist/ ./monitor/static/react_dashboard/

# Persistent data directory for SQLite
RUN mkdir -p /app/data

RUN python manage.py collectstatic --noinput

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "Uniwatch.wsgi:application"]
