"""
Example: Using JupySQL Database Providers

This example demonstrates how to use the database provider system
to discover and connect to databases from various sources.
"""

from sql.connection import ConnectionManager
from sql.providers import get_factory

# =============================================================================
# Example 1: List all available providers
# =============================================================================
print("=" * 80)
print("Example 1: List all registered providers")
print("=" * 80)

factory = get_factory()
providers = factory.list_providers()

print(f"\nRegistered providers: {providers}")

for provider_name in providers:
    provider = factory.get_provider(provider_name)
    status = "enabled" if provider.is_enabled() else "disabled"
    print(f"  - {provider_name}: {status}")

# =============================================================================
# Example 2: List all available databases from all providers
# =============================================================================
print("\n" + "=" * 80)
print("Example 2: List all available databases")
print("=" * 80)

databases = factory.list_databases()

print(f"\nFound {len(databases)} databases:")
for db in databases:
    print(f"\n  {db.name}")
    print(f"    Provider: {db.provider}")
    print(f"    Identifier: {db.identifier}")
    print(f"    Host: {db.host}:{db.port}")
    print(f"    Database: {db.database}")
    print(f"    Username: {db.username}")
    if db.labels:
        print(f"    Labels: {db.labels}")

# =============================================================================
# Example 3: List databases from specific providers
# =============================================================================
print("\n" + "=" * 80)
print("Example 3: List databases from CNPG provider only")
print("=" * 80)

cnpg_databases = factory.list_databases(provider_names=["cnpg"])

print(f"\nFound {len(cnpg_databases)} CNPG databases:")
for db in cnpg_databases:
    print(f"  - {db.name}")

# =============================================================================
# Example 4: Get a specific database by identifier
# =============================================================================
print("\n" + "=" * 80)
print("Example 4: Get a specific database by identifier")
print("=" * 80)

if databases:
    # Get the first available database
    first_db = databases[0]
    print(f"\nLooking up database: {first_db.identifier}")

    db_info = factory.get_database(first_db.identifier)
    if db_info:
        print(f"  Found: {db_info.name}")
        print(f"  Connection string: {db_info.connection_string[:50]}...")
    else:
        print("  Not found")

# =============================================================================
# Example 5: Refresh providers to discover new databases
# =============================================================================
print("\n" + "=" * 80)
print("Example 5: Refresh providers")
print("=" * 80)

print("\nRefreshing all providers...")
factory.refresh_all()
print("Done!")

print("\nRefreshing only CNPG provider...")
factory.refresh_provider("cnpg")
print("Done!")

# =============================================================================
# Example 6: Connect to a database from a provider
# =============================================================================
print("\n" + "=" * 80)
print("Example 6: Connect to a database from a provider")
print("=" * 80)

if databases:
    # Connect to the first available database
    first_db = databases[0]
    print(f"\nConnecting to: {first_db.name}")

    try:
        conn = ConnectionManager.connect_from_provider(
            identifier=first_db.identifier,
            alias="example-connection"
        )
        print(f"  Connected successfully!")
        print(f"  Connection alias: {conn.alias}")
        print(f"  Connection URL: {str(conn.url)[:50]}...")

        # Now you can use this connection with %sql magic
        # %sql SELECT 1 as test

    except Exception as e:
        print(f"  Failed to connect: {e}")

# =============================================================================
# Example 7: Working with ConnectionManager
# =============================================================================
print("\n" + "=" * 80)
print("Example 7: Using ConnectionManager methods")
print("=" * 80)

# List available databases via ConnectionManager
print("\nListing available databases via ConnectionManager:")
available = ConnectionManager.list_available_databases()
print(f"  Found {len(available)} databases")

# Refresh providers via ConnectionManager
print("\nRefreshing providers via ConnectionManager:")
ConnectionManager.refresh_providers()
print("  Done!")

# =============================================================================
# Example 8: Filter databases by metadata
# =============================================================================
print("\n" + "=" * 80)
print("Example 8: Filter databases by metadata")
print("=" * 80)

databases = factory.list_databases()

# Filter CNPG clusters (not poolers)
clusters = [
    db for db in databases
    if db.metadata.get("source") == "cnpg_cluster"
]
print(f"\nCNPG Clusters: {len(clusters)}")
for db in clusters:
    print(f"  - {db.name}")

# Filter CNPG read-write poolers
rw_poolers = [
    db for db in databases
    if db.metadata.get("source") == "cnpg_pooler"
    and db.metadata.get("pooler_type") == "rw"
]
print(f"\nRead-Write Poolers: {len(rw_poolers)}")
for db in rw_poolers:
    print(f"  - {db.name}")

# Filter by labels
print(f"\nDatabases with label 'environment=production':")
prod_dbs = [
    db for db in databases
    if db.labels.get("environment") == "production"
]
for db in prod_dbs:
    print(f"  - {db.name}")

# =============================================================================
# Example 9: Working with the Static Provider
# =============================================================================
print("\n" + "=" * 80)
print("Example 9: Adding databases to the Static Provider")
print("=" * 80)

from sql.providers.static import StaticDatabaseProvider
from sql.providers.base import DatabaseInfo

# Get the static provider
static_provider = factory.get_provider("static")

if isinstance(static_provider, StaticDatabaseProvider):
    # Add a custom database
    custom_db = DatabaseInfo(
        identifier="custom:my-database",
        name="My Custom Database",
        connection_string="postgresql://user:pass@localhost:5432/mydb",
        provider="static",
        metadata={"custom": True},
        host="localhost",
        port=5432,
        database="mydb",
        username="user",
    )

    static_provider.add_database(custom_db)
    print(f"\nAdded custom database: {custom_db.name}")

    # List all databases (including the new one)
    all_dbs = factory.list_databases()
    print(f"\nTotal databases: {len(all_dbs)}")

    # Remove the custom database
    static_provider.remove_database(custom_db.identifier)
    print(f"\nRemoved custom database")

print("\n" + "=" * 80)
print("Examples completed!")
print("=" * 80)
