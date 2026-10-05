"""Production WSGI entrypoint for Railway/Gunicorn."""
from app import app, init_db

# Ensure the PostgreSQL schema exists before the web worker begins serving.
init_db()

application = app
