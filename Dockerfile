FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SQLITE_PATH=/var/lib/datasetcleanser/db.sqlite3 \
    PRIVATE_FILE_ROOT=/var/lib/datasetcleanser/files

WORKDIR /app
COPY dataset_cleanser/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0

RUN useradd --system --user-group --uid 10001 cleanser \
    && install -d -o cleanser -g cleanser /var/lib/datasetcleanser
COPY dataset_cleanser/ ./
USER cleanser

EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "dataset_cleanser.wsgi:application"]
