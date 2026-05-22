ARG PYTHON_VERSION=3.12.0
FROM python:${PYTHON_VERSION}-slim as base
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml .
RUN python -m pip install uv && \
    uv pip install --system -e . && \
    pip install "faststream[cli]"
COPY . .
EXPOSE 8012
CMD alembic upgrade head && \
    (faststream run app.fs.app:app &) && \
    uvicorn 'app.main:app' --host=0.0.0.0 --port=8012
