FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir flask psycopg2-binary gunicorn

# Copy application
COPY src/ /app/
COPY templates/ /app/templates/

# Expose port
EXPOSE 8080

# Run with gunicorn with increased timeout
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "4", "--timeout", "120", "app:app"]
