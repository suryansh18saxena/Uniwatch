# Uniwatch Setup Guide

Welcome to the Uniwatch project! This guide will help you set up the development environment locally.

## Prerequisites

- **Python 3.9+**
- **Docker & Docker Compose** (for running Prometheus locally)
- **Git**

## 1. Clone & Environment Setup

```bash
git clone <repository_url>
cd uniwatch

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## 2. Environment Variables

Copy the example environment file and configure it if necessary:

```bash
cp .env.example .env
```

## 3. Database Setup

We use SQLite for local development by default. Run the migrations:

```bash
python manage.py migrate
```

Optionally, create a superuser for the admin panel:

```bash
python manage.py createsuperuser
```

## 4. Run Prometheus

Uniwatch requires Prometheus to collect metrics. We've included a standalone configuration for local development.

Make sure you are in the project root, then start Prometheus:

```bash
# If you have Prometheus installed locally:
prometheus --config.file=prometheus/prometheus.yml

# Or using Docker Compose (if provided in your setup):
# cd prometheus && docker-compose up -d
```

> **Note on Targets:** The Django app will automatically write to `prometheus/targets/uniwatch_targets.json` when you add a new server via the web UI.

## 5. Run the Local Server

Start the Django development server:

```bash
python manage.py runserver
```

You can now access the platform at: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

## 6. Accessing the Admin Panel

The admin panel is available at [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/). Here you can view managed servers, registered alerts, and the fix execution audit history.

---

### Important Development Notes
- **Security:** SSH keys uploaded via the UI are *never* stored in the database. They are kept in memory solely for the duration of the setup script and immediately garbage collected.
- **Auto-Fix Permissions:** Review `monitor/fix_actions.py` when adding new self-healing capabilities. All production commands must be mapped here and passed against the internal blacklist.
