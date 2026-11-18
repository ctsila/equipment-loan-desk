FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DB_PATH=/data/loans.sqlite
RUN mkdir /data && chown 10001:10001 /data
COPY service.py .
USER 10001:10001
VOLUME ["/data"]
EXPOSE 8080
CMD ["python", "service.py"]
