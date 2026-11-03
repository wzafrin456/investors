FROM python:3.11-slim

WORKDIR /app
COPY . /app

ENV PORT=8080
ENV PYTHONUNBUFFERED=1

EXPOSE 8080
CMD ["python", "gcp/app.py"]

