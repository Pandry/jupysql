# Multi-stage Dockerfile for JupySQL with JupyterLab Extension
# Stage 1: Build the JupyterLab extension
FROM docker.io/library/python:3.11-slim AS builder

# Install Node.js and build dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy package files first for better caching
COPY package.json setup.py setup.cfg pyproject.toml MANIFEST.in README.md ./
COPY jupysql_labextension/package.json jupysql_labextension/
COPY jupysql_labextension/tsconfig.json jupysql_labextension/

# Install Python dependencies (provides jupyter labextension build command)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir 'jupyterlab>=4.0.0,<5'

# Copy source code
COPY src/ src/
COPY jupysql_labextension/src/ jupysql_labextension/src/
COPY jupysql_labextension/style/ jupysql_labextension/style/
COPY jupyter-config/ jupyter-config/

# Build the JupyterLab extension
WORKDIR /build/jupysql_labextension
RUN npm install && \
    npm run build:lib && \
    npm run build:labextension:dev

# databao-agent's release files were removed from PyPI: build a wheel of its
# last tag here, where Node is available for its frontend (built with pnpm)
RUN npm install -g pnpm@10.14.0 && \
    pip wheel --no-cache-dir --no-deps -w /wheels \
        'databao-agent @ git+https://github.com/JetBrains/databao-agent@v0.2.3'

# Stage 2: Final image with JupySQL installed
FROM docker.io/library/python:3.11-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    sqlite3 \
    curl \
    git \
    texlive-xetex \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy built extension and source from builder
COPY --from=builder /build/ /app/
COPY --from=builder /wheels/ /wheels/

# Install JupySQL with the built extension
RUN pip install --no-cache-dir --upgrade pip && \
    # jupyterhub must match the hub's major version: z2jh chart 4.4.x runs
    # JupyterHub 5.5, so stay on 5.x until the chart moves to 6
    pip install --no-cache-dir 'jupyterlab>=4.0.0,<5' 'jupyterhub>=5.0,<6' 'jupyter-collaboration>=3.0,<4'

RUN pip install -e . && \
    # Mandatory DB
    pip install --no-cache-dir psycopg2-binary matplotlib pandas \
    # Kubernetes client for CNPG provider
    kubernetes \
    # Jupytext for declarative notebooks
    jupytext \
    # ipywidgets
    ipywidgets \
    # Voila dashboards with gridstack layout
    voila voila-gridstack \
    # Chat
    jupyterlab-chat \
    # Git
    jupyterlab-git \
    # Renderers
    jupyterlab-fasta jupyterlab-geojson jupyterlab-katex \
    # LaTex
    jupyterlab-latex \
    # Databao (databao-agent wheel built in the builder stage)
    /wheels/databao_agent-*.whl databao-context-engine \
    #DuckDB
    duckdb duckdb-engine \
    # SQLAlchemy 2.1 reflects Postgres collations via pg_catalog.pg_collation,
    # which DuckDB lacks: duckdb-engine (0.17.0) column inspection fails
    # (JupySQL's %sqlcmd columns, likely marimo's data sources panel too).
    # Drop once duckdb-engine supports 2.1.
    'sqlalchemy<2.1' \
    # Numpy
    numpy \
    # Marimo
    # (recommended: SQL cells via polars/pyarrow, altair for the data sources
    # panel, ruff formatting; lsp: completions/diagnostics in the editor)
    'marimo[recommended,lsp]>=0.25.0' 'marimo-jupyter-extension>=0.5.0'


# pip install -e does not reliably copy data_files for editable installs in
# modern pip (PEP 660).  Copy both artefacts explicitly.

# 1. JupyterLab frontend extension → labextensions directory
RUN mkdir -p /usr/local/share/jupyter/labextensions/jupysql-labextension && \
    cp -r jupysql/labextension/. /usr/local/share/jupyter/labextensions/jupysql-labextension/

# 2. Jupyter Server extension config → sys-prefix config dir so the server
#    picks it up at startup without needing 'jupyter server extension enable'
# 3. Server settings (config.d files only carry jpserver_extensions): run
#    marimo without its default uv sandbox, which creates a fresh
#    per-notebook venv that can't see the packages installed above
RUN mkdir -p /usr/local/etc/jupyter/jupyter_server_config.d/ && \
    cp jupyter-config/jupyter_server_config.d/jupysql.json \
       /usr/local/etc/jupyter/jupyter_server_config.d/jupysql.json && \
    cp jupyter-config/jupyter_server_config.json \
       /usr/local/etc/jupyter/jupyter_server_config.json

# Verify installation
RUN jupyter server extension list && \
    jupyter labextension list

RUN useradd -m -u 1000 -g 100 -d /home/shared -s /bin/bash jupyter

# Create IPython startup script to auto-load %sql magic and auto-connect
# provider-discovered databases (e.g. CNPG clusters).
# Note: Requires volume mount at a subdirectory (e.g., /home/shared/notebooks)
#       not at /home/shared itself, to preserve this directory
RUN mkdir -p /home/shared/.ipython/profile_default/startup
COPY scripts/00-jupysql-autoload.py /app/scripts/00-jupysql-autoload.py
RUN cp scripts/00-jupysql-autoload.py /home/shared/.ipython/profile_default/startup/00-jupysql-autoload.py && \
    chown -R 1000:100 /home/shared/.ipython

USER jupyter
WORKDIR /home/shared


# Expose JupyterLab port
EXPOSE 8888

# Set environment variables
ENV JUPYTER_ENABLE_LAB=yes

# CNPG Database Provider Configuration
ENV JUPYSQL_CNPG_ENABLED=true
# ENV JUPYSQL_CNPG_NAMESPACE=database-ns,analytics-ns
ENV JUPYSQL_CNPG_LABEL_SELECTOR=jupysql.pandry.github.io/enabled=true
ENV JUPYSQL_CNPG_AUTO_REFRESH_INTERVAL=100
ENV JUPYSQL_CNPG_DEBOUNCE_INTERVAL=5
ENV JUPYSQL_CNPG_NAMESPACE=*

# Run JupyterLab
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--ServerApp.token=''", "--ServerApp.password=''", "--ServerApp.disable_check_xsrf=True"]
