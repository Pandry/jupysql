# Multi-stage Dockerfile for JupySQL with JupyterLab Extension
# Stage 1: Build the JupyterLab extension
FROM docker.io/library/python:3.11-slim AS builder

# Install Node.js and build dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
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

# Verify the build output
RUN ls -la ../jupysql/labextension/ || echo "Warning: labextension directory not created"

# Stage 2: Final image with JupySQL installed
FROM docker.io/library/python:3.11-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy built extension and source from builder
COPY --from=builder /build/ /app/

# Install JupySQL with the built extension
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir 'jupyterlab>=4.0.0,<5' 'jupyterhub>=5.0,<6' 'jupyter-collaboration>=3.0,<4'

# Binaries
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install -e . && \
    # Mandatory DB
    pip install --no-cache-dir psycopg2-binary duckdb-engine matplotlib pandas \
    # Chat 
    jupyterlab-chat \
    # Git
    jupyterlab-git \
    # Renderers
    jupyterlab-fasta jupyterlab-geojson jupyterlab-katex jupyterlab-mathjax2 jupyterlab-vega3 \
    # LaTex
    jupyterlab-latex
    

# pip install -e does not reliably copy data_files for editable installs in
# modern pip (PEP 660).  Copy both artefacts explicitly.

# 1. JupyterLab frontend extension → labextensions directory
RUN mkdir -p /usr/local/share/jupyter/labextensions/jupysql-labextension && \
    cp -r jupysql/labextension/. /usr/local/share/jupyter/labextensions/jupysql-labextension/

# 2. Jupyter Server extension config → sys-prefix config dir so the server
#    picks it up at startup without needing 'jupyter server extension enable'
RUN mkdir -p /usr/local/etc/jupyter/jupyter_server_config.d/ && \
    cp jupyter-config/jupyter_server_config.d/jupysql.json \
       /usr/local/etc/jupyter/jupyter_server_config.d/jupysql.json

# Verify installation
RUN jupyter server extension list && \
    jupyter labextension list

RUN useradd -m -u 1000 -g 100 -d /home/shared -s /bin/bash jupyter

USER jupyter
WORKDIR /home/shared


# Expose JupyterLab port
EXPOSE 8888

# Set environment variables
ENV JUPYTER_ENABLE_LAB=yes

# Run JupyterLab
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--ServerApp.token=''", "--ServerApp.password=''", "--ServerApp.disable_check_xsrf=True"]
