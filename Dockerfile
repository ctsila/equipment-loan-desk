FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DB_PATH=/data/requests.sqlite
RUN mkdir /data && chown 10001:10001 /data
COPY service.py accounts.json ./
COPY public/ public/
USER 10001:10001
VOLUME ["/data"]
EXPOSE 8080
CMD ["python", "service.py"]
