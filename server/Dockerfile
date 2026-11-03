# Zero Day relay server (only the relay, not the game).
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt relay.py ./
RUN pip install --no-cache-dir -r requirements.txt
ENV PORT=8080
EXPOSE 8080
CMD ["python", "relay.py"]
