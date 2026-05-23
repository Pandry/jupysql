# Dockerfile for JupySQL with JupyterLab Extension
#
# The labextension is pre-built locally (npm run build:lib && npm run
# build:labextension:dev) and committed to jupysql/labextension/.
# This avoids Node.js version issues in the container build.
FROM docker.io/library/python:3.11-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    sqlite3 \
    curl \
    git \
    texlive-xetex \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy entire project
COPY . /app/

# Install JupySQL with the pre-built extension
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir 'jupyterlab>=4.0.0,<5' 'jupyterhub>=5.0,<6' 'jupyter-collaboration>=3.0,<4'

RUN pip install -e . && \
    # Mandatory DB
    pip install --no-cache-dir psycopg2-binary duckdb-engine matplotlib pandas \
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

# Create IPython startup script to auto-load %sql magic and auto-connect
# provider-discovered databases (e.g. CNPG clusters).
# Note: Requires volume mount at a subdirectory (e.g., /home/shared/notebooks)
#       not at /home/shared itself, to preserve this directory
RUN mkdir -p /home/shared/.ipython/profile_default/startup && \
    cp scripts/00-jupysql-autoload.py /home/shared/.ipython/profile_default/startup/00-jupysql-autoload.py && \
    chown -R 1000:100 /home/shared/.ipython

USER jupyter
WORKDIR /home/shared


# Expose JupyterLab port
EXPOSE 8888

# Set environment variables
ENV JUPYTER_ENABLE_LAB=yes

# CNPG Database Provider Configuration
# Enable CNPG provider (set to "false" to disable automatic discovery of CNPG clusters)
ENV JUPYSQL_CNPG_ENABLED=true

# Kubernetes namespace(s) to search for CNPG clusters
# - Not set or empty: auto-detect from service account, or cluster-wide if not in K8s
# - "*" or "all": query all namespaces (requires ClusterRole RBAC)
# - "ns1,ns2,ns3": query multiple specific namespaces
# - "single-ns": query only that namespace
# ENV JUPYSQL_CNPG_NAMESPACE=database-ns,analytics-ns

# Label selector for filtering CNPG clusters and poolers (default: jupysql.pandry.github.io/enabled=true)
# Examples:
#   - jupysql.pandry.github.io/enabled=true (default)
#   - app=myapp,environment=production
#   - jupysql.pandry.github.io/enabled=true,tenant=acme
ENV JUPYSQL_CNPG_LABEL_SELECTOR=jupysql.pandry.github.io/enabled=true

# Auto-refresh interval in seconds (default: 100)
# How often to automatically refresh the list of available databases
ENV JUPYSQL_CNPG_AUTO_REFRESH_INTERVAL=100

# Debounce interval in seconds (default: 5)
# Minimum time between manual refresh requests to prevent K8s API spam
ENV JUPYSQL_CNPG_DEBOUNCE_INTERVAL=5
ENV JUPYSQL_CNPG_NAMESPACE=*

# Run JupyterLab
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--ServerApp.token=''", "--ServerApp.password=''", "--ServerApp.disable_check_xsrf=True"]
