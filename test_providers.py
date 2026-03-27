#!/usr/bin/env python3
"""
Quick validation script for the database provider system.
Run this after installing JupySQL to verify the implementation.

Usage:
    python test_providers.py
"""

import sys


def test_imports():
    """Test that all provider modules can be imported."""
    print("Testing imports...")
    try:
        from sql.providers import get_factory, DatabaseProvider, DatabaseInfo
        from sql.providers.base import DatabaseProvider, DatabaseInfo
        from sql.providers.factory import DatabaseProviderFactory, get_factory
        from sql.providers.static import StaticDatabaseProvider
        from sql.providers.config_file import ConfigFileDatabaseProvider
        from sql.providers.cnpg import CNPGDatabaseProvider
        print("  ✓ All imports successful")
        return True
    except ImportError as e:
        print(f"  ✗ Import failed: {e}")
        return False


def test_factory():
    """Test that the factory can be instantiated."""
    print("\nTesting factory...")
    try:
        from sql.providers import get_factory
        factory = get_factory()
        print(f"  ✓ Factory created: {factory}")

        # Test singleton pattern
        factory2 = get_factory()
        if factory is factory2:
            print("  ✓ Singleton pattern works")
        else:
            print("  ✗ Singleton pattern broken")
            return False

        return True
    except Exception as e:
        print(f"  ✗ Factory test failed: {e}")
        return False


def test_static_provider():
    """Test static provider functionality."""
    print("\nTesting static provider...")
    try:
        from sql.providers.static import StaticDatabaseProvider
        from sql.providers.base import DatabaseInfo

        provider = StaticDatabaseProvider()
        print(f"  ✓ Static provider created: {provider.name}")

        # Test adding a database
        db = DatabaseInfo(
            identifier="test:db1",
            name="Test Database",
            connection_string="sqlite:///:memory:",
            provider="static",
        )
        provider.add_database(db)
        print("  ✓ Added test database")

        # Test listing
        databases = provider.list_databases()
        if len(databases) == 1 and databases[0].identifier == "test:db1":
            print("  ✓ List databases works")
        else:
            print(f"  ✗ Expected 1 database, got {len(databases)}")
            return False

        # Test getting specific database
        retrieved = provider.get_database("test:db1")
        if retrieved and retrieved.identifier == "test:db1":
            print("  ✓ Get database works")
        else:
            print("  ✗ Get database failed")
            return False

        # Test removing
        removed = provider.remove_database("test:db1")
        if removed and len(provider.list_databases()) == 0:
            print("  ✓ Remove database works")
        else:
            print("  ✗ Remove database failed")
            return False

        return True
    except Exception as e:
        print(f"  ✗ Static provider test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_config_file_provider():
    """Test config file provider functionality."""
    print("\nTesting config file provider...")
    try:
        from sql.providers.config_file import ConfigFileDatabaseProvider
        import tempfile
        import os

        # Create a temporary config file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as f:
            f.write("""[test_db]
drivername = sqlite
database = :memory:

[another_db]
drivername = postgresql
username = user
password = pass
host = localhost
port = 5432
database = testdb
""")
            config_path = f.name

        try:
            provider = ConfigFileDatabaseProvider(config_path=config_path)
            print(f"  ✓ Config file provider created: {provider.name}")

            # Test listing
            databases = provider.list_databases()
            if len(databases) >= 2:
                print(f"  ✓ Found {len(databases)} databases from config file")
            else:
                print(f"  ✗ Expected at least 2 databases, got {len(databases)}")
                return False

            # Test getting specific database
            test_db = provider.get_database("config_file:test_db")
            if test_db and test_db.name == "test_db":
                print("  ✓ Get database from config file works")
            else:
                print("  ✗ Get database from config file failed")
                return False

            return True
        finally:
            os.unlink(config_path)

    except Exception as e:
        print(f"  ✗ Config file provider test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_cnpg_provider():
    """Test CNPG provider initialization (doesn't require K8s to be available)."""
    print("\nTesting CNPG provider...")
    try:
        from sql.providers.cnpg import CNPGDatabaseProvider
        import os

        # Ensure CNPG is disabled for testing
        os.environ['JUPYSQL_CNPG_ENABLED'] = 'false'

        provider = CNPGDatabaseProvider()
        print(f"  ✓ CNPG provider created: {provider.name}")
        print(f"  ✓ CNPG provider enabled: {provider.is_enabled()}")

        # Test that it doesn't crash when disabled
        databases = provider.list_databases()
        print(f"  ✓ List databases works (found {len(databases)})")

        return True
    except ImportError as e:
        if "kubernetes" in str(e).lower():
            print("  ⚠ Kubernetes package not installed (optional)")
            print("    Install with: pip install kubernetes")
            return True  # Not a failure, just optional
        print(f"  ✗ CNPG provider test failed: {e}")
        return False
    except Exception as e:
        print(f"  ✗ CNPG provider test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_factory_registration():
    """Test provider registration with factory."""
    print("\nTesting factory registration...")
    try:
        from sql.providers import get_factory
        from sql.providers.static import StaticDatabaseProvider

        factory = get_factory()

        # Register a provider
        provider = StaticDatabaseProvider()
        factory.register_provider(provider)
        print("  ✓ Registered provider")

        # Check it's registered
        providers = factory.list_providers()
        if "static" in providers:
            print(f"  ✓ Provider registered (total: {len(providers)})")
        else:
            print("  ✗ Provider not found in factory")
            return False

        # Get the provider back
        retrieved = factory.get_provider("static")
        if retrieved is provider:
            print("  ✓ Retrieved same provider instance")
        else:
            print("  ✗ Retrieved different provider instance")
            return False

        return True
    except Exception as e:
        print(f"  ✗ Factory registration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_connection_manager_integration():
    """Test ConnectionManager integration."""
    print("\nTesting ConnectionManager integration...")
    try:
        from sql.connection import ConnectionManager

        # Check new methods exist
        if not hasattr(ConnectionManager, 'list_available_databases'):
            print("  ✗ ConnectionManager missing list_available_databases method")
            return False
        print("  ✓ list_available_databases method exists")

        if not hasattr(ConnectionManager, 'refresh_providers'):
            print("  ✗ ConnectionManager missing refresh_providers method")
            return False
        print("  ✓ refresh_providers method exists")

        if not hasattr(ConnectionManager, 'connect_from_provider'):
            print("  ✗ ConnectionManager missing connect_from_provider method")
            return False
        print("  ✓ connect_from_provider method exists")

        return True
    except Exception as e:
        print(f"  ✗ ConnectionManager integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("=" * 80)
    print("JupySQL Database Provider System - Validation Tests")
    print("=" * 80)

    tests = [
        ("Imports", test_imports),
        ("Factory", test_factory),
        ("Static Provider", test_static_provider),
        ("Config File Provider", test_config_file_provider),
        ("CNPG Provider", test_cnpg_provider),
        ("Factory Registration", test_factory_registration),
        ("ConnectionManager Integration", test_connection_manager_integration),
    ]

    results = {}
    for name, test_func in tests:
        results[name] = test_func()

    # Summary
    print("\n" + "=" * 80)
    print("Test Summary")
    print("=" * 80)

    passed = sum(1 for result in results.values() if result)
    total = len(results)

    for name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")

    print("\n" + "=" * 80)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 80)

    if passed == total:
        print("\n🎉 All tests passed! The provider system is working correctly.")
        return 0
    else:
        print(f"\n⚠ {total - passed} test(s) failed. Please check the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
