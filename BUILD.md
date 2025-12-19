# Building JupySQL with JupyterLab Extension

This guide explains how to build and run JupySQL with the JupyterLab sidebar extension.

## Prerequisites

The easiest way to build and run JupySQL is using Docker (no local setup required).

### Option 1: Using Docker (Recommended)

**Requirements:**
- Docker and Docker Compose installed

**Build and run:**
```bash
# Build and start JupyterLab
docker-compose up jupysql

# Or run in detached mode
docker-compose up -d jupysql

# View logs
docker-compose logs -f jupysql

# Stop
docker-compose down
```

JupyterLab will be available at: http://localhost:8888

Your notebooks will be saved in the `./notebooks` directory.

### Option 2: Local Development

**Requirements:**
- Python 3.8+
- Node.js 16+ and npm

**Setup:**
```bash
# 1. Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install Python dependencies
pip install -r requirements.txt
pip install jupyterlab>=4.0.0

# 3. Build the JupyterLab extension
cd jupysql_labextension
npm install
npm run build
cd ..

# 4. Install JupySQL in editable mode
pip install -e .

# 5. Enable the server extension
jupyter server extension enable sql.labextension

# 6. Start JupyterLab
jupyter lab
```

## Development Mode

For active development with hot-reloading:

```bash
# Using Docker
docker-compose up jupysql-dev

# Or locally in two terminals:

# Terminal 1: Watch TypeScript changes
cd jupysql_labextension
npm run watch

# Terminal 2: Run JupyterLab with watch mode
jupyter lab --watch
```

## Verifying Installation

Check that the extension is installed:

```bash
# Check server extension
jupyter server extension list

# Check JupyterLab extension
jupyter labextension list
```

You should see:
- `sql.labextension` in the server extensions list
- `jupysql-labextension` in the JupyterLab extensions list

## Using the Extension

Once JupyterLab is running:

1. Look for the database icon in the left sidebar
2. Create a SQL connection in a notebook:
   ```python
   %load_ext sql
   %sql sqlite:///mydata.db --alias mydb
   ```
3. The sidebar will show your connection and allow you to browse:
   - Schemas
   - Tables
   - Columns with data types

## Troubleshooting

### Extension not showing in sidebar
- Check that both server and labextension are enabled (see Verifying Installation above)
- Try rebuilding: `cd jupysql_labextension && npm run build`
- Restart JupyterLab

### Build errors
- Ensure Node.js 16+ is installed: `node --version`
- Clear build artifacts: `cd jupysql_labextension && npm run clean && npm install`
- Check TypeScript compilation: `npm run build:lib`

### Docker issues
- Rebuild the image: `docker-compose build --no-cache jupysql`
- Check logs: `docker-compose logs jupysql`

## Project Structure

```
jupysql/
├── src/sql/                    # Python package
│   └── labextension/          # Server extension (REST API)
├── jupysql_labextension/      # JupyterLab extension
│   └── src/                   # TypeScript/React code
│       ├── components/        # UI components
│       │   └── DatabaseTree.tsx
│       ├── services/          # API client
│       └── sidebar.tsx        # Main sidebar component
├── jupysql/labextension/      # Built extension output
├── Dockerfile                 # Docker build configuration
└── docker-compose.yml         # Docker Compose configuration
```

## Clean Build

To start fresh:

```bash
# Clean all build artifacts
cd jupysql_labextension
npm run clean
cd ..

# Remove built extension
rm -rf jupysql/labextension

# Rebuild
cd jupysql_labextension
npm install
npm run build
cd ..

pip install -e .
```
