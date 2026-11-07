FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080
COPY config ./config
COPY data ./data
COPY output ./output
COPY radar ./radar
COPY gcp ./gcp
EXPOSE 8080
CMD ["python", "gcp/app.py"]
