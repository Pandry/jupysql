import os
from io import open
import re
import ast

from setuptools import find_packages, setup

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, "README.md"), encoding="utf-8").read()

_version_re = re.compile(r"__version__\s+=\s+(.*)")

with open("src/sql/__init__.py", "rb") as f:
    VERSION = str(
        ast.literal_eval(_version_re.search(f.read().decode("utf-8")).group(1))
    )

LAB_EXT_NAME = "jupysql-labextension"
LAB_EXT_SRC = "jupysql/labextension"


def _collect_data_files():
    """Collect data_files for setup(), including the built JupyterLab extension."""
    files = [
        (
            "etc/jupyter/jupyter_server_config.d",
            ["jupyter-config/jupyter_server_config.d/jupysql.json"],
        ),
    ]
    # Include the pre-built JupyterLab extension bundle if it exists.
    # The bundle is produced by `npm run build:labextension:dev` (see Dockerfile /
    # COMPILE.md).  During `pip install -e .` inside Docker the directory is already
    # present; outside Docker it may be absent, which is fine – the extension will
    # simply not be registered as a labextension until the npm build is run.
    if os.path.isdir(LAB_EXT_SRC):
        dest_prefix = f"share/jupyter/labextensions/{LAB_EXT_NAME}"
        for root, _dirs, fnames in os.walk(LAB_EXT_SRC):
            rel = os.path.relpath(root, LAB_EXT_SRC)
            dest = dest_prefix if rel == "." else os.path.join(dest_prefix, rel)
            file_paths = [os.path.join(root, f) for f in fnames]
            if file_paths:
                files.append((dest, file_paths))
    return files


install_requires = [
    "prettytable>=3.12.0",
    # IPython dropped support for Python 3.8
    "ipython<=8.12.0; python_version <= '3.8'",
    "sqlalchemy",
    "sqlparse",
    "ipython-genutils>=0.1.0",
    "jinja2",
    "sqlglot>=11.3.7",
    'importlib-metadata;python_version<"3.8"',
    # we removed the share notebook button in this version
    "jupysql-plugin>=0.4.2",
    "ploomber-core>=0.2.7",
    # Server extension for JupyterLab
    "jupyter-server>=2.0.0",
]

DEV = [
    "flake8",
    "pytest",
    # 24/01/24 Pandas 2.2.0 breaking CI: https://github.com/ploomber/jupysql/issues/983
    "pandas<2.2.0",  # previously pinned to 2.0.3
    "polars==0.17.2",  # 04/18/23 this breaks our CI
    "pyarrow",
    "invoke",
    "pkgmt",
    "twine",
    # tests
    "duckdb<1.1.0",
    "duckdb-engine",
    "pyodbc",
    # sql.plot module tests
    "matplotlib==3.7.2",
    "black",
    # for %%sql --interact
    "ipywidgets",
    # for running tests for %sqlcmd explore --table
    "js2py",
    # for monitoring access to files
    "psutil",
    # for running tests for %sqlcmd connect
    "jupyter-server",
]

# dependencies for running integration tests
INTEGRATION = [
    "dockerctx",
    "pyarrow",
    "psycopg2-binary",
    "pymysql",
    "pgspecial==2.0.1",
    "pyodbc",
    "snowflake-sqlalchemy",
    "oracledb",
    "sqlalchemy-pytds",
    "python-tds",
    # redshift
    "redshift-connector",
    "sqlalchemy-redshift",
    "clickhouse-sqlalchemy",
    # following two dependencies required for spark
    "pyspark",
    "grpcio-status",
]

# dependencies for CNPG provider (Kubernetes integration)
CNPG = [
    "kubernetes>=28.0.0",
]

setup(
    name="jupysql",
    version=VERSION,
    description="Better SQL in Jupyter",
    long_description=README,
    long_description_content_type="text/markdown",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Console",
        "License :: OSI Approved :: Apache Software License",
        "Topic :: Database",
        "Topic :: Database :: Front-Ends",
        "Programming Language :: Python :: 3",
    ],
    keywords="database ipython postgresql mysql duckdb analysis jupyter sql",
    author="Pandry (original work by Ploomber and Catherine Devlin)",
    author_email="",
    url="https://github.com/Pandry/jupysql",
    project_urls={
        "Source": "https://github.com/Pandry/jupysql",
        "Documentation": "https://pandry.github.io/jupysql/",
        "Original Project": "https://github.com/ploomber/jupysql",
    },
    packages=find_packages("src"),
    package_dir={"": "src"},
    include_package_data=True,
    zip_safe=False,
    install_requires=install_requires,
    extras_require={
        "dev": DEV,
        "integration": DEV + INTEGRATION,
        "cnpg": CNPG,
        "all": DEV + INTEGRATION + CNPG,
    },
    entry_points={
        "jupyter_serverproxy_servers": [
            # For Jupyter Server Proxy if needed
        ]
    },
    # Register Jupyter Server extension and JupyterLab extension
    data_files=_collect_data_files(),
)
