FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev
COPY src/ ./src/
COPY streamlit_app/ ./streamlit_app/
COPY fixtures/ ./fixtures/
ENV AGENTOPS_PROVIDER=local-fake
ENV AGENTOPS_DATABASE_URL=sqlite:///./agentops.db
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "agentops_workbench.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
