# JupySQL with JupyterLab Extension - Setup Instructions

## Current Status

✅ **Phase 1 & 2 Complete** - Infrastructure and Backend Ready!

### What's Been Implemented

**Python Package (✅ Installed)**
- In-notebook widgets: `DatabaseBrowserWidget`, `DatabaseSelectorWidget`, `TableWidget`
- Server extension: REST API handlers for connections, schemas, tables, columns
- Backend: All Python code is ready and functional

**JupyterLab Extension (⏳ Pending Node.js)**
- TypeScript/React code structure created
- Build configuration ready
- Requires Node.js to compile

## Installation Complete (Python Only)

The Python package is now installed in editable mode. You can use:

```python
from sql.widgets import DatabaseBrowserWidget, DatabaseSelectorWidget

# In-notebook browser widget
browser = DatabaseBrowserWidget()
browser

# In-notebook connection selector
selector = DatabaseSelectorWidget()
selector
```

## Next Steps

### To Build the JupyterLab Extension

**1. Install Node.js** (if not already installed)
```bash
# Option 1: Using Homebrew (macOS)
brew install node

# Option 2: Download from https://nodejs.org/

# Verify installation
node --version
npm --version
```

**2. Uncomment Build Configuration**

Edit `pyproject.toml` and uncomment all the sections marked with:
```toml
# For now, use setuptools for compatibility
# Uncomment the sections below when ready to build the JupyterLab extension
```

**3. Build the Extension**

```bash
# Activate virtual environment
source venv/bin/activate

# Install npm dependencies
cd jupysql_labextension
npm install  # or: jlpm install

# Build the extension
npm run build  # or: jlpm run build

# Go back to root
cd ..
```

**4. Reinstall jupysql** (to include the built extension)

```bash
# After building, reinstall
pip install -e .

# Or use the full hatchling build
# (Uncomment pyproject.toml first)
# pip uninstall jupysql
# pip install -e .
```

**5. Enable Server Extension**

```bash
# Enable the server extension
jupyter server extension enable sql.labextension

# List enabled extensions (verify it's there)
jupyter server extension list
```

**6. Start JupyterLab**

```bash
jupyter lab
```

The sidebar should appear with the database browser icon on the left!

## Testing Without JupyterLab Extension

You can test the functionality now using the in-notebook widgets:

```python
# Load the SQL magic
%load_ext sql

# Create a connection
%sql sqlite:///test.db --alias testdb

# Use the browser widget
from sql.widgets import DatabaseBrowserWidget
browser = DatabaseBrowserWidget()
browser  # This will show connections, schemas, tables, columns

# Use the selector widget
from sql.widgets import DatabaseSelectorWidget
selector = DatabaseSelectorWidget()
selector
```

## What's Available Now (Without Node.js)

✅ **In-Notebook Widgets** - Fully functional
- `DatabaseBrowserWidget` - Tree view browser
- `DatabaseSelectorWidget` - Connection switcher
- `TableWidget` - Table preview

✅ **Server Extension** - Ready to use
- REST API endpoints at `/jupysql/*`
- All handlers implemented
- Credential obfuscation working

⏳ **JupyterLab Sidebar Extension** - Needs Node.js to build
- TypeScript/React code written
- Will provide persistent sidebar panel
- More features than in-notebook widgets

## Development Workflow (With Node.js)

Once Node.js is installed:

```bash
# Terminal 1: Watch TypeScript compilation
cd jupysql_labextension
npm run watch

# Terminal 2: Run JupyterLab with hot reload
jupyter lab --watch
```

Any changes to TypeScript files will auto-rebuild and reload in JupyterLab!

## Files Created

### Python Backend
- `src/sql/labextension/__init__.py` - Extension entry point
- `src/sql/labextension/app.py` - Server extension app
- `src/sql/labextension/handlers.py` - REST API handlers (365 lines)

### TypeScript Frontend
- `jupysql_labextension/src/index.ts` - Extension entry point
- `jupysql_labextension/src/sidebar.tsx` - Sidebar component (pending full implementation)
- `jupysql_labextension/package.json` - Build configuration
- `jupysql_labextension/tsconfig.json` - TypeScript configuration

### Configuration
- `package.json` - Root npm configuration
- `pyproject.toml` - Python build configuration (hatchling disabled until Node.js available)
- `install.json` - JupyterLab extension metadata
- `MANIFEST.in` - Updated to include extension files

## API Endpoints (Server Extension)

Once the server extension is enabled:

- `GET /jupysql/connections` - List all connections
- `POST /jupysql/connections` - Add new connection
- `GET /jupysql/schemas` - Get schemas for connection
- `GET /jupysql/tables` - Get tables for schema
- `GET /jupysql/columns` - Get columns for table
- `GET /jupysql/preview` - Get table data preview
- `POST /jupysql/switch` - Switch active connection

## Troubleshooting

### "pip install -e ." fails
- Make sure you're in the virtual environment: `source venv/bin/activate`
- The installation should work now using setup.py (Node.js not required)

### Extension not loading in JupyterLab
- Make sure Node.js is installed
- Build the extension: `cd jupysql_labextension && npm run build`
- Enable server extension: `jupyter server extension enable sql.labextension`
- Check: `jupyter labextension list`

### "Node.js required" error
- You can use the Python package without Node.js
- The JupyterLab sidebar extension requires Node.js to build
- In-notebook widgets work without Node.js

## Next Implementation Phases

**Phase 3: Frontend Components** (Requires Node.js)
- API client service
- DatabaseTree React component with lazy loading
- Full sidebar with connection management
- JupyterLab theme integration

**Phase 4: User Interactions**
- Connection form dialog
- Context menus (copy, insert, preview)
- Table preview panel
- Column selection for query generation

## Questions?

Check the detailed implementation plan:
```bash
cat /Users/andrea/.claude/plans/drifting-meandering-grove.md
```

Or review the documentation files:
- `DATABASE_WIDGETS.md` - Widget user documentation
- `WIDGET_IMPLEMENTATION.md` - Implementation details
