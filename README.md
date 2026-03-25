# JupySQL
![CI](https://github.com/Pandry/jupysql/workflows/CI/badge.svg)
![CI Integration Tests](https://github.com/Pandry/jupysql/actions/workflows/ci-integration-db.yaml/badge.svg)
![Broken Links](https://github.com/Pandry/jupysql/workflows/check-for-broken-links/badge.svg)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

<p align="center">
  <a href="https://pandry.github.io/jupysql/">Documentation</a>
  |
  <a href="https://github.com/Pandry/jupysql/issues">Issues</a>
  |
  <a href="#contributing">Contributing</a>
</p>

> [!NOTE]
> **JupySQL is a powerful SQL analysis tool for Jupyter.** This project serves as a modern replacement for [Briefer](https://github.com/briefercloud/briefer) (now closed) for data analysis workflows in Jupyter notebooks.

Run SQL in Jupyter/IPython via `%sql` and `%%sql` magics.

## Features

- [Pandas integration](https://pandry.github.io/jupysql/integrations/pandas.html)
- [SQL composition (no more hard-to-debug CTEs!)](https://pandry.github.io/jupysql/compose.html)
- [Plot massive datasets without blowing up memory](https://pandry.github.io/jupysql/plot.html)
- [DuckDB integration](https://pandry.github.io/jupysql/integrations/duckdb.html)
- **JupyterLab Extension** - Database browser sidebar for exploring connections, schemas, tables, and columns

## Installation

### From PyPI (Standard)

```bash
pip install jupysql
```

or with conda:

```bash
conda install jupysql -c conda-forge
```

### From Git (Latest)

To install the latest development version directly from this repository:

```bash
pip install git+https://github.com/Pandry/jupysql.git
```

### Using Docker (Recommended for Full Experience)

The Docker image includes JupySQL with the JupyterLab extension and all optional dependencies:

```bash
# Using docker-compose
docker-compose up jupysql

# Or using docker directly
docker pull ghcr.io/pandry/jupysql:latest
docker run -p 8888:8888 -v $(pwd):/home/shared ghcr.io/pandry/jupysql:latest
```

Access JupyterLab at `http://localhost:8888` (no token required in default config).

### JupyterLab Extension (Optional)

For the database browser sidebar in JupyterLab, use the Docker installation above or see [BUILD.md](BUILD.md) for local development setup.

After making code changes, see [COMPILE.md](COMPILE.md) for compilation instructions.

## Documentation

[Click here to see the documentation.](https://pandry.github.io/jupysql)

## Security

To report security vulnerabilities, see [SECURITY.md](SECURITY.md)

## Credits

This project is a continuation fork originally based on work by [Ploomber](https://github.com/ploomber/jupysql), which itself was a fork of [ipython-sql](https://github.com/catherinedevlin/ipython-sql) by Catherine Devlin.

**Acknowledgments:**
- **Ploomber Team**: For the significant development work that transformed ipython-sql into a full-featured SQL client for Jupyter, including the JupyterLab extension, plotting capabilities, and modern integrations. While Ploomber's commercial operations have concluded, their open-source contributions live on in this project.
- **Catherine Devlin**: For creating the original ipython-sql project that started it all.
- **Community Contributors**: Everyone who has contributed to these projects over the years.

This fork maintains and extends the excellent foundation built by these teams, focusing on data analysis workflows and serving as a modern alternative to now-closed projects like Briefer.

## Contributing

We welcome contributions! Please feel free to:
- Report bugs or request features via [GitHub Issues](https://github.com/Pandry/jupysql/issues)
- Submit pull requests
- Improve documentation

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.
