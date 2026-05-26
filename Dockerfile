FROM python:3.11-slim

WORKDIR /srv

COPY app/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium

COPY app/ ./app/

EXPOSE 8000

CMD ["python", "-m", "app.api.main"]
