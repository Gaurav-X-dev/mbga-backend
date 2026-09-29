FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip

# Dependencies first, so a code change does not reinstall them.
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .

# Alembic is not part of the installed package, but the container is what runs the upgrade:
# without these the image starts against a database that has no tables.
COPY alembic.ini ./alembic.ini
COPY database ./database
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh

# Credentials and uploaded documents are mounted at run time, never baked into the image:
# an image is copied and pushed, and anything inside it travels with it.
RUN mkdir -p /app/secrets /app/var/documents \
    && useradd --system --uid 10001 mbga \
    && chown -R mbga:mbga /app/var
USER mbga

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
