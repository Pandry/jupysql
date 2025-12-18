# Database Browser and Selector Widgets

JupySQL now includes two powerful widgets for managing and exploring database connections directly in Jupyter notebooks:

## DatabaseBrowserWidget

A tree-view widget that allows you to visually explore your database structure.

### Features

- **Hierarchical View**: Browse connections → schemas → tables → columns
- **Expandable Tree**: Click to expand/collapse each level
- **Column Information**: View column names and data types
- **Multi-Connection Support**: Browse all connected databases
- **Credential Protection**: Passwords and sensitive info automatically hidden
- **Current Connection Indicator**: Shows which connection is active

### Usage

```python
from sql.widgets import DatabaseBrowserWidget

# Display the browser
browser = DatabaseBrowserWidget()
browser
```

The widget will display:
- 🔌 **Connections**: All database connections (with obfuscated URLs)
- 📁 **Schemas**: Schemas within each connection
- 📊 **Tables**: Tables within each schema
- ▪ **Columns**: Columns with their data types

## DatabaseSelectorWidget

A dropdown widget for quickly switching between database connections.

### Features

- **Quick Switching**: Select and switch with one click
- **Current Indicator**: Shows which connection is currently active
- **Success Feedback**: Visual confirmation of successful switches
- **Error Handling**: Clear error messages if switching fails
- **Credential Protection**: Only shows aliases or obfuscated URLs

### Usage

```python
from sql.widgets import DatabaseSelectorWidget

# Display the selector
selector = DatabaseSelectorWidget()
selector
```

## Complete Example

```python
# Load the SQL magic
%load_ext sql

# Create multiple connections
%sql postgresql://user:pass@localhost/db1 --alias production
%sql postgresql://user:pass@localhost/db2 --alias staging
%sql sqlite:///local.db --alias local

# Import widgets
from sql.widgets import DatabaseBrowserWidget, DatabaseSelectorWidget

# Display selector to switch between connections
selector = DatabaseSelectorWidget()
display(selector)

# Display browser to explore database structure
browser = DatabaseBrowserWidget()
display(browser)

# Now you can:
# 1. Use the selector to switch between databases
# 2. Use the browser to explore the active database structure
# 3. Run queries on the active connection
%sql SELECT * FROM my_table
```

## Security Features

Both widgets are designed with security in mind:

1. **Password Obfuscation**: Database passwords are automatically replaced with `***`
2. **Safe URL Display**: Connection strings are sanitized before display
3. **Alias Priority**: When available, aliases are shown instead of full URLs
4. **No Credential Storage**: Widgets don't store or log sensitive information

## How It Works

### Under the Hood

1. **ConnectionManager Integration**: Widgets directly access the ConnectionManager which already handles credential obfuscation
2. **Jupyter Comms**: Uses Jupyter's communication protocol for frontend-backend interaction
3. **SQLAlchemy Inspector**: Leverages SQLAlchemy's inspection capabilities to query database metadata
4. **Connection Switching**: Temporarily switches connections to inspect different databases without affecting user queries

### Credential Protection

The widgets use the existing JupySQL infrastructure which:
- Stores obfuscated URLs in `ConnectionManager.connections`
- Uses SQLAlchemy's URL representation that automatically masks passwords
- Only displays aliases or sanitized connection strings

Example:
```
Actual:     postgresql://admin:secret123@prod-server.com:5432/mydb
Displayed:  postgresql://admin:***@prod-server.com:5432/mydb
Or (if alias): production
```

## Browser Compatibility

The widgets work in:
- **Jupyter Notebook** (Classic)
- **JupyterLab** (3.0+)
- **Google Colab**
- **VS Code Jupyter Extension**

Note: Requires `jupysql-plugin>=0.4.2` (already included in dependencies)

## Supported Databases

The widgets support all databases that JupySQL supports:
- PostgreSQL
- MySQL / MariaDB
- SQLite
- DuckDB
- Microsoft SQL Server
- Oracle
- Snowflake
- And more...

For DBAPI connections (non-SQLAlchemy), the widgets show a simplified view with limited schema information.

## Tips

1. **Refresh**: To refresh the browser after schema changes, simply re-instantiate the widget:
   ```python
   browser = DatabaseBrowserWidget()
   ```

2. **Multiple Views**: You can create multiple instances of each widget in different cells

3. **Combine with Commands**: Use alongside `%sqlcmd` commands for a complete database management experience:
   ```python
   %sqlcmd tables
   %sqlcmd columns --table my_table
   ```

## Troubleshooting

**Widget not displaying?**
- Ensure `jupysql-plugin>=0.4.2` is installed
- Restart the Jupyter kernel
- Check browser console for JavaScript errors

**Can't see schemas/tables?**
- Ensure you have proper database permissions
- Some databases may require explicit schema names
- DBAPI connections have limited introspection capabilities

**Connection switching not working?**
- Verify the connection is still active
- Check that you have multiple connections established
- Look for error messages in the widget status area

## Architecture

```
┌─────────────────────────────────────┐
│         Jupyter Notebook            │
│                                     │
│  ┌─────────────────────────────┐  │
│  │   Widget HTML/CSS/JS         │  │
│  │   (Frontend Display)         │  │
│  └──────────┬──────────────────┘  │
│             │ Jupyter Comm         │
│  ┌──────────▼──────────────────┐  │
│  │   Widget Python Class        │  │
│  │   (Backend Logic)            │  │
│  └──────────┬──────────────────┘  │
│             │                      │
│  ┌──────────▼──────────────────┐  │
│  │   ConnectionManager          │  │
│  │   (Credentials Hidden)       │  │
│  └──────────┬──────────────────┘  │
│             │                      │
│  ┌──────────▼──────────────────┐  │
│  │   SQLAlchemy Inspector       │  │
│  │   (Database Metadata)        │  │
│  └─────────────────────────────┘  │
└─────────────────────────────────────┘
```

## Contributing

Found a bug or have a feature request? Please open an issue on the [JupySQL GitHub repository](https://github.com/ploomber/jupysql).
