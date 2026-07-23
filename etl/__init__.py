"""
CRMArena ETL (Extract, Transform, Load) Package

This package contains tools for syncing CRMArena schema and data to Salesforce.

Python Modules:
    - export_schema: Export schema from Salesforce to JSON
    - sync_schema_to_salesforce: Sync schema to Salesforce (create objects/fields)
    - upload_data_to_salesforce: Upload data from SQLite to Salesforce
    - cleanup_salesforce_data: Clean up data in Salesforce org
    - check_storage: Check storage usage in Salesforce org
    - test_salesforce_connection: Test Salesforce connection
    - test_scratch_org_connection: Test scratch org connection

Shell Scripts:
    - create_scratch_org.sh: Create a Salesforce scratch org
    - setup_devhub.sh: Set up DevHub for scratch org creation

Usage:
    cd CRMArena/etl
    ./setup_devhub.sh              # Set up DevHub (one-time)
    ./create_scratch_org.sh        # Create scratch org
    python sync_schema_to_salesforce.py --org_type original
    python upload_data_to_salesforce.py --org_type original
"""

__version__ = "1.0.0"

