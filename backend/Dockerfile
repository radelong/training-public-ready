FROM python:3.12.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY assets/wheels /wheels
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-index --find-links=/wheels -r requirements.txt && rm -rf /wheels && useradd -r -u 10001 academy
COPY --chown=10001:10001 backend/academy /app/academy
COPY --chown=10001:10001 frontend /app/frontend
COPY --chown=10001:10001 catalogue.json /app/catalogue.json
USER 10001
EXPOSE 8000
CMD ["uvicorn", "academy.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]
