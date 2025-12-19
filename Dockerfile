# Multi-stage Dockerfile for JupySQL with JupyterLab Extension
# Stage 1: Build the JupyterLab extension
FROM python:3.11-slim as builder

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
COPY package.json setup.py setup.cfg pyproject.toml MANIFEST.in ./
COPY jupysql_labextension/package.json jupysql_labextension/
COPY jupysql_labextension/tsconfig.json jupysql_labextension/

# Copy source code
COPY src/ src/
COPY jupysql/ jupysql/
COPY jupysql_labextension/src/ jupysql_labextension/src/
COPY jupysql_labextension/style/ jupysql_labextension/style/
COPY jupyter-config/ jupyter-config/

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir 'jupyterlab>=4.0.0,<5'

# Build the JupyterLab extension
WORKDIR /build/jupysql_labextension
RUN npm install && \
    npm run build:lib && \
    npm run build:labextension:dev

# Verify the build output
RUN ls -la ../jupysql/labextension/ || echo "Warning: labextension directory not created"

# Stage 2: Final image with JupySQL installed
FROM python:3.11-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy built extension and source from builder
COPY --from=builder /build/ /app/

# Install JupySQL in editable mode with the built extension
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir 'jupyterlab>=4.0.0,<5' && \
    pip install -e .

# Enable the Jupyter Server extension
RUN jupyter server extension enable sql.labextension

# Verify installation
RUN jupyter server extension list && \
    jupyter labextension list

# Create a workspace directory for notebooks
WORKDIR /workspace

# Expose JupyterLab port
EXPOSE 8888

# Set environment variables
ENV JUPYTER_ENABLE_LAB=yes

# Run JupyterLab
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--NotebookApp.token=''", "--NotebookApp.password=''"]
