FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
ENV PYTHONUNBUFFERED=1
RUN mkdir /data /status /cache && chown nobody /data /status /cache
USER nobody
CMD ["python", "scraper.py"]
