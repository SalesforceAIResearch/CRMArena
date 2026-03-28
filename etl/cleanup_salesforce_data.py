#!/usr/bin/env python3
"""
Cleanup script to delete data from Salesforce org to free up storage.

Usage:
    python cleanup_salesforce_data.py --org_type original --object Account --limit 100
    python cleanup_salesforce_data.py --org_type original --all-objects --confirm
"""

import argparse
import os
import subprocess
import json
from dotenv import load_dotenv
from simple_salesforce import Salesforce
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# Objects to clean up (in reverse dependency order)
CLEANUP_ORDER = [
    "CaseHistory__c",
    "EmailMessage",
    "Knowledge__kav",
    "OrderItem",
    "Order",
    "Case",
    "PricebookEntry",
    "Contact",
    "Product2",
    "Pricebook2",
    "Issue__c",
    "Account",
]

class SalesforceCleaner:
    def __init__(self, org_type: str = "original"):
        """Initialize the cleaner."""
        # Load .env from parent directory (CRMArena root) or current directory
        env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
        if os.path.exists(env_path):
            load_dotenv(env_path)
        else:
            load_dotenv()  # Fallback to default search
        self.org_type = org_type
        
        # Get credentials
        if org_type == "b2b":
            username = os.getenv("SALESFORCE_B2B_USERNAME")
            password = os.getenv("SALESFORCE_B2B_PASSWORD")
            security_token = os.getenv("SALESFORCE_B2B_SECURITY_TOKEN")
        elif org_type == "b2c":
            username = os.getenv("SALESFORCE_B2C_USERNAME")
            password = os.getenv("SALESFORCE_B2C_PASSWORD")
            security_token = os.getenv("SALESFORCE_B2C_SECURITY_TOKEN")
        else:  # original
            username = os.getenv("SALESFORCE_USERNAME")
            password = os.getenv("SALESFORCE_PASSWORD")
            security_token = os.getenv("SALESFORCE_SECURITY_TOKEN")
        
        # Connect to Salesforce
        print(f"Connecting to Salesforce ({org_type})...")
        
        # Try username/password first
        if all([username, password, security_token]):
            try:
                self.sf = Salesforce(username=username, password=password, security_token=security_token)
                print("✅ Connected using username/password!")
                return
            except Exception as e:
                print(f"⚠️  Username/password authentication failed: {e}")
                print("   Trying access token method (for scratch orgs)...")
        
        # Fallback: Try access token from Salesforce CLI
        try:
            access_token, instance_url = self._get_access_token_from_cli()
            if access_token and instance_url:
                self.sf = Salesforce(instance_url=instance_url, session_id=access_token)
                print("✅ Connected using access token from Salesforce CLI!")
                return
        except Exception as e:
            pass
        
        raise ValueError(f"Could not connect to Salesforce. Check credentials or run 'sf org login web'.")
    
    def _get_access_token_from_cli(self) -> Tuple[Optional[str], Optional[str]]:
        """Get access token from Salesforce CLI."""
        # Method 1: Try the default target-org
        try:
            result = subprocess.run(
                ['sf', 'config', 'get', 'target-org', '--json'],
                capture_output=True, text=True, check=True
            )
            config_data = json.loads(result.stdout)
            default_org = None
            result_list = config_data.get('result', [])
            if isinstance(result_list, list) and len(result_list) > 0:
                default_org = result_list[0].get('value', '')
            
            if default_org:
                result2 = subprocess.run(
                    ['sf', 'org', 'display', '--target-org', default_org, '--json'],
                    capture_output=True, text=True, check=True
                )
                data = json.loads(result2.stdout)
                access_token = data.get('result', {}).get('accessToken', '')
                instance_url = data.get('result', {}).get('instanceUrl', '')
                if access_token and instance_url:
                    print(f"   Using default target-org: {default_org}")
                    return access_token, instance_url
        except:
            pass
        
        # Method 2: Try any available scratch org
        try:
            result = subprocess.run(
                ['sf', 'org', 'list', '--json'],
                capture_output=True, text=True, check=True
            )
            data = json.loads(result.stdout)
            scratch_orgs = data.get('result', {}).get('scratchOrgs', [])
            for org in scratch_orgs:
                if org.get('isExpired', False):
                    continue
                alias = org.get('alias', org.get('username', ''))
                if alias:
                    result2 = subprocess.run(
                        ['sf', 'org', 'display', '--target-org', alias, '--json'],
                        capture_output=True, text=True, check=True
                    )
                    data2 = json.loads(result2.stdout)
                    access_token = data2.get('result', {}).get('accessToken', '')
                    instance_url = data2.get('result', {}).get('instanceUrl', '')
                    if access_token and instance_url:
                        print(f"   Using scratch org: {alias}")
                        return access_token, instance_url
        except:
            pass
        
        return None, None
    
    def get_record_count(self, object_name: str) -> int:
        """Get the number of records for an object."""
        try:
            result = self.sf.query(f"SELECT COUNT() FROM {object_name}")
            return result['totalSize']
        except Exception as e:
            print(f"  ⚠️  Could not get count for {object_name}: {e}")
            return 0
    
    def delete_object_records(self, object_name: str, limit: Optional[int] = None, confirm: bool = False) -> dict:
        """Delete records from an object using Bulk API for speed."""
        print(f"\n🗑️  Cleaning up {object_name}...")
        
        # Special handling for Knowledge articles
        if object_name == "Knowledge__kav":
            print(f"  ⚠️  Knowledge articles require special handling - skipping")
            print(f"  💡 Delete Knowledge articles manually in Salesforce UI or use Data Loader")
            return {"deleted": 0, "errors": 0, "skipped": True}
        
        # Get record count
        total_count = self.get_record_count(object_name)
        if total_count == 0:
            print(f"  ℹ️  No records found for {object_name}")
            return {"deleted": 0, "errors": 0}
        
        print(f"  Found {total_count:,} records")
        
        if not confirm:
            print(f"  ⚠️  DRY RUN - use --confirm to actually delete")
            return {"deleted": 0, "errors": 0}
        
        # Query records to delete - get ALL if no limit specified
        query_limit = limit if limit else total_count
        query = f"SELECT Id FROM {object_name} LIMIT {query_limit}"
        
        try:
            result = self.sf.query_all(query)
            records = result['records']
            
            if not records:
                print(f"  ℹ️  No records to delete")
                return {"deleted": 0, "errors": 0}
            
            print(f"  Deleting {len(records):,} records (sequential with progress)...")
            
            ids_to_delete = [r['Id'] for r in records]
            deleted = 0
            errors = 0
            total = len(ids_to_delete)
            
            try:
                for i, rid in enumerate(ids_to_delete):
                    try:
                        self.sf.__getattr__(object_name).delete(rid)
                        deleted += 1
                    except:
                        errors += 1
                    
                    # Show progress every 1000 records
                    if (i + 1) % 1000 == 0 or (i + 1) == total:
                        pct = ((i + 1) / total) * 1000
                        print(f"    {i + 1:,}/{total:,} ({pct:.0f}%) - {deleted:,} deleted, {errors} errors", flush=True)
                
                print(f"  ✅ Total: {deleted:,} deleted, {errors} errors")
                
            except Exception as bulk_error:
                # Fallback to REST API if Bulk API fails
                print(f"  ⚠️  Bulk API failed, falling back to REST API: {str(bulk_error)[:50]}")
                batch_size = 200  # Larger batches for REST API
                max_workers = 20  # More parallel threads
                
                def delete_record(record_id):
                    """Delete a single record."""
                    try:
                        self.sf.__getattr__(object_name).delete(record_id)
                        return {"success": True}
                    except Exception as e:
                        error_msg = str(e)
                        if "INVALID_CROSS_REFERENCE_KEY" in error_msg or "ENTITY_IS_DELETED" in error_msg:
                            return {"success": True}
                        else:
                            return {"success": False, "error": error_msg}
                
                ids_list = [r['Id'] for r in records]
                total_batches = (len(ids_list) + batch_size - 1) // batch_size
                
                for i in range(0, len(ids_list), batch_size):
                    batch = ids_list[i:i + batch_size]
                    batch_num = (i // batch_size) + 1
                    
                    print(f"    Batch {batch_num}/{total_batches} ({len(batch)} records)...", end="", flush=True)
                    
                    batch_deleted = 0
                    batch_errors = 0
                    
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = [executor.submit(delete_record, rid) for rid in batch]
                        for future in as_completed(futures):
                            result = future.result()
                            if result["success"]:
                                batch_deleted += 1
                            else:
                                batch_errors += 1
                    
                    deleted += batch_deleted
                    errors += batch_errors
                    print(f" ✅ ({batch_deleted} deleted, {batch_errors} errors)")
                
                print(f"  ✅ Total: {deleted:,} deleted, {errors} errors")
            
            # If many errors, suggest checking dependencies
            if errors > len(ids_to_delete) * 0.1:  # More than 10% errors
                print(f"  💡 Tip: Many errors may indicate dependency issues. Try deleting child objects first.")
            
            return {"deleted": deleted, "errors": errors}
            
        except Exception as e:
            error_msg = str(e)
            if "INVALID_TYPE" in error_msg or "sObject type" in error_msg:
                print(f"  ⚠️  Object {object_name} not found or not accessible - skipping")
                return {"deleted": 0, "errors": 0, "skipped": True}
            else:
                print(f"  ❌ Delete failed: {e}")
                return {"deleted": 0, "errors": 1}
    
    def cleanup_all(self, limit_per_object: Optional[int] = None, confirm: bool = False):
        """Clean up all objects in dependency order."""
        print("\n" + "="*60)
        print("Cleaning Up Salesforce Data")
        print("="*60)
        
        if not confirm:
            print("\n⚠️  DRY RUN MODE - No data will be deleted")
            print("   Use --confirm to actually delete records\n")
        
        total_deleted = 0
        total_errors = 0
        skipped_objects = []
        
        for object_name in CLEANUP_ORDER:
            result = self.delete_object_records(object_name, limit=limit_per_object, confirm=confirm)
            total_deleted += result['deleted']
            total_errors += result['errors']
            if result.get('skipped'):
                skipped_objects.append(object_name)
        
        print("\n" + "="*60)
        print("Cleanup Summary")
        print("="*60)
        print(f"Total records deleted: {total_deleted:,}")
        print(f"Total errors: {total_errors}")
        if skipped_objects:
            print(f"Skipped objects: {', '.join(skipped_objects)}")
        print("="*60)

def main():
    parser = argparse.ArgumentParser(
        description="Clean up data from Salesforce org to free up storage"
    )
    parser.add_argument(
        "--org_type",
        type=str,
        default="original",
        choices=["original", "b2b", "b2c"],
        help="Organization type"
    )
    parser.add_argument(
        "--object",
        type=str,
        help="Specific object to clean up (e.g., Account, Case)"
    )
    parser.add_argument(
        "--all-objects",
        action="store_true",
        help="Clean up all objects"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of records to delete per object"
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete records (required for deletion)"
    )
    parser.add_argument(
        "--clear-mappings",
        action="store_true",
        help="Also clear ID mappings database after cleanup"
    )
    
    args = parser.parse_args()
    
    if not args.object and not args.all_objects:
        parser.error("Must specify either --object or --all-objects")
    
    try:
        cleaner = SalesforceCleaner(org_type=args.org_type)
        
        if args.all_objects:
            cleaner.cleanup_all(limit_per_object=args.limit, confirm=args.confirm)
        else:
            cleaner.delete_object_records(args.object, limit=args.limit, confirm=args.confirm)
        
        # Clear ID mappings if requested
        if args.clear_mappings and args.confirm:
            import sqlite3
            # Default path now in local_data/id_mappings.db at project root
            project_root = os.path.dirname(os.path.dirname(__file__))
            id_mapping_db_path = os.path.join(project_root, "local_data", "id_mappings.db")
            if os.path.exists(id_mapping_db_path):
                conn = sqlite3.connect(id_mapping_db_path)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM id_mappings")
                conn.commit()
                conn.close()
                print("\n🗑️  ID mappings database cleared.")
        
        return 0
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())

