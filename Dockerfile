FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml README.md ./
COPY src ./src
COPY agents ./agents

RUN uv pip install --system -e .

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "odk_platform.main:app", "--host", "0.0.0.0", "--port", "8000"]
