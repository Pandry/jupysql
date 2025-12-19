# How to Compile the JupyterLab Extension

After making changes to TypeScript files (`.tsx`, `.ts`), you need to compile them.

## Quick Start (Docker)

**Easiest method - Everything is automated:**

```bash
# Build the Docker image (compiles automatically)
docker-compose build --no-cache jupysql

# Run JupyterLab
docker-compose up jupysql

# Access at http://localhost:8888
```

## Local Development (No Docker)

### Prerequisites
You need Node.js 16+ installed:
```bash
node --version  # Should be 16 or higher
```

### First Time Setup

```bash
# Install Node dependencies
cd jupysql_labextension
npm install  # or: jlpm install

# Go back to root
cd ..
```

### Compile After Code Changes

Every time you change `.tsx` or `.ts` files:

```bash
cd jupysql_labextension

# Option 1: Quick build (development mode)
npm run build
# This runs: tsc && jupyter labextension build --development

# Option 2: Production build (optimized)
npm run build:prod

# Option 3: Watch mode (auto-recompile on file changes)
npm run watch
# Leave this running while you develop!
```

### Install the Compiled Extension

```bash
# From project root
cd /Users/andrea/code/jupysql

# Install in editable mode
pip install -e .

# Enable server extension
jupyter server extension enable sql.labextension

# Start JupyterLab
jupyter lab
```

## Verify Compilation

Check that the extension compiled:

```bash
# Should see compiled JS files
ls -la jupysql/labextension/

# Check TypeScript compilation
ls -la jupysql_labextension/lib/

# Verify installation
jupyter labextension list
jupyter server extension list
```

## What Gets Compiled?

```
Source (you edit):                  Compiled (auto-generated):
├── jupysql_labextension/src/      →  ├── jupysql_labextension/lib/
│   ├── components/                    │   ├── components/
│   │   └── DatabaseTree.tsx           │   │   └── DatabaseTree.js
│   ├── services/                      │   └── ...
│   └── sidebar.tsx                    └── jupysql/labextension/
                                           └── static/
                                               └── (bundled JS/CSS)
```

## Development Workflow

### Method 1: Watch Mode (Recommended)
```bash
# Terminal 1: Auto-compile on changes
cd jupysql_labextension
npm run watch

# Terminal 2: Run JupyterLab with hot reload
jupyter lab --watch
```

Now when you edit `.tsx` files, they auto-compile and JupyterLab reloads!

### Method 2: Manual Rebuild
```bash
# Edit code...
cd jupysql_labextension
npm run build
cd ..

# Restart JupyterLab
jupyter lab
```

### Method 3: Docker (No local Node.js needed)
```bash
# Edit code...
docker-compose build jupysql
docker-compose up jupysql
```

## Troubleshooting

### "tsc: command not found"
```bash
cd jupysql_labextension
npm install
```

### Build errors
```bash
# Clean and rebuild
cd jupysql_labextension
npm run clean
npm install
npm run build
```

### Extension not updating
```bash
# Hard rebuild
cd jupysql_labextension
npm run clean:all
npm install
npm run build
cd ..
pip install -e . --force-reinstall
jupyter lab build
```

## Current Changes

The latest fix for the 3-click bug is in:
- `jupysql_labextension/src/components/DatabaseTree.tsx`

You MUST compile this file for the changes to take effect!
