FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AGENT_BROWSER_HEADLESS=true
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY requirements-runtime.txt .
RUN pip install --no-cache-dir -r requirements-runtime.txt && python -m playwright install --with-deps chromium
COPY . .
CMD ["python","agent_supervisor.py"]
