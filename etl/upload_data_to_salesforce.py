#!/usr/bin/env python3
"""
Upload CRMArena data from SQLite database to Salesforce Developer org.

This script:
1. Reads data from local_data/crmarena_data_xxx.db for original/b2b/b2c
2. Handles relationships and ID mapping
3. Uploads records to Salesforce in the correct order
4. Uses Salesforce Bulk API for efficient uploads

Usage:
    python upload_data_to_salesforce.py --org_type original [--dry-run] [--limit N]
"""

import sqlite3
import json
import os
import argparse
import time
import subprocess
import sys
import io
import atexit
import re
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from dotenv import load_dotenv
from simple_salesforce import Salesforce
import pandas as pd


class Tee(io.TextIOBase):
    """Simple tee to write output to both console and a log file."""
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for stream in self.streams:
            try:
                stream.write(s)
            except Exception:
                # Best-effort logging; don't break on log errors
                pass
        return len(s)

    def flush(self):
        for stream in self.streams:
            try:
                stream.flush()
            except Exception:
                pass


# Set up log file under logs/etl/upload_data/
try:
    _project_root = os.path.dirname(os.path.dirname(__file__))
    _log_dir = os.path.join(_project_root, "logs", "etl", "upload_data")
    os.makedirs(_log_dir, exist_ok=True)
    _timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_path = os.path.join(_log_dir, f"upload_{_timestamp}.log")
    _log_file = open(_log_path, "w", encoding="utf-8")

    # Tee stdout and stderr to the log file
    sys.stdout = Tee(sys.stdout, _log_file)
    sys.stderr = Tee(sys.stderr, _log_file)

    def _close_log_file():
        try:
            _log_file.close()
        except Exception:
            pass

    atexit.register(_close_log_file)
except Exception:
    # If logging setup fails, continue with normal stdout/stderr
    pass


class IdMappingDB:
    """SQLite-based persistent storage for ID mappings between source and Salesforce."""
    
    def __init__(self, db_path: str = None):
        """Initialize the ID mapping database."""
        if db_path is None:
            # Default path: local_data/id_mappings.db at project root
            project_root = os.path.dirname(os.path.dirname(__file__))
            local_data_dir = os.path.join(project_root, "local_data")
            os.makedirs(local_data_dir, exist_ok=True)
            db_path = os.path.join(local_data_dir, "id_mappings.db")

        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._create_tables()
        
        # In-memory cache for faster lookups
        self._cache: Dict[str, Dict[str, str]] = {}
        self._load_cache()
    
    def _create_tables(self):
        """Create the ID mapping tables if they don't exist."""
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS id_mappings (
                object_name TEXT NOT NULL,
                old_id TEXT NOT NULL,
                new_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (object_name, old_id)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_object_old 
            ON id_mappings(object_name, old_id)
        ''')
        self.conn.commit()
    
    def _load_cache(self):
        """Load all mappings into memory for fast lookups."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT object_name, old_id, new_id FROM id_mappings')
        for row in cursor.fetchall():
            object_name, old_id, new_id = row
            if object_name not in self._cache:
                self._cache[object_name] = {}
            self._cache[object_name][old_id] = new_id
    
    def get_mapping(self, object_name: str, old_id: str) -> Optional[str]:
        """Get the new Salesforce ID for an old source ID."""
        if not old_id:
            return None
        old_id_str = str(old_id)
        
        # Check cache first
        if object_name in self._cache:
            return self._cache[object_name].get(old_id_str)
        
        return None
    
    def save_mapping(self, object_name: str, old_id: str, new_id: str):
        """Save a single ID mapping."""
        if not old_id or not new_id:
            return
        
        old_id_str = str(old_id)
        cursor = self.conn.cursor()
        created_at = datetime.utcnow().isoformat()
        cursor.execute('''
            INSERT OR REPLACE INTO id_mappings (object_name, old_id, new_id, created_at)
            VALUES (?, ?, ?, ?)
        ''', (object_name, old_id_str, new_id, created_at))
        self.conn.commit()
        
        # Update cache
        if object_name not in self._cache:
            self._cache[object_name] = {}
        self._cache[object_name][old_id_str] = new_id
    
    def save_mappings_batch(self, object_name: str, mappings: List[Tuple[str, str]]):
        """Save multiple ID mappings in a batch for better performance."""
        if not mappings:
            return
        
        cursor = self.conn.cursor()
        now_str = datetime.utcnow().isoformat()
        
        data = [(object_name, str(old_id), new_id, now_str) for old_id, new_id in mappings if old_id and new_id]
        
        cursor.executemany('''
            INSERT OR REPLACE INTO id_mappings (object_name, old_id, new_id, created_at)
            VALUES (?, ?, ?, ?)
        ''', data)
        self.conn.commit()
        
        # Update cache
        if object_name not in self._cache:
            self._cache[object_name] = {}
        for old_id, new_id in mappings:
            if old_id and new_id:
                self._cache[object_name][str(old_id)] = new_id
    
    def get_count(self, object_name: str = None) -> int:
        """Get count of mappings, optionally filtered by object."""
        cursor = self.conn.cursor()
        if object_name:
            cursor.execute('SELECT COUNT(*) FROM id_mappings WHERE object_name = ?', (object_name,))
        else:
            cursor.execute('SELECT COUNT(*) FROM id_mappings')
        return cursor.fetchone()[0]
    
    def get_all_for_object(self, object_name: str) -> Dict[str, str]:
        """Get all mappings for an object."""
        return self._cache.get(object_name, {})
    
    def clear_object(self, object_name: str):
        """Clear all mappings for an object."""
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM id_mappings WHERE object_name = ?', (object_name,))
        self.conn.commit()
        if object_name in self._cache:
            del self._cache[object_name]
    
    def clear_all(self):
        """Clear all mappings."""
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM id_mappings')
        self.conn.commit()
        self._cache = {}
    
    def close(self):
        """Close the database connection."""
        self.conn.close()


# Object upload order (respecting dependencies)
UPLOAD_ORDER = [
    "User",           # No dependencies
    "Account",        # No dependencies
    "Lead",           # No dependencies (needed by Opportunity, Task, Event, LiveChatTranscript, etc.)
    "Territory2",     # No dependencies
    "UserTerritory2Association", # Depends on: User, Territory2
    "ProductCategory", # No dependencies
    "Product2",       # No dependencies
    "Pricebook2",     # No dependencies
    "PricebookEntry", # Depends on: Pricebook2, Product2
    "Contact",        # Depends on: Account, User
    "Opportunity",    # Depends on: Account, Contact (optional), Pricebook2 (optional)
    "OpportunityLineItem", # Depends on: Opportunity, Product2, PricebookEntry
    "Contract",       # Depends on: Account
    "Quote",          # Depends on: Opportunity, Account, Contact (optional)
    "QuoteLineItem",  # Depends on: Quote, Product2, PricebookEntry
    "Issue__c",       # No dependencies
    "Order",          # Depends on: Account, Pricebook2, Contract (optional)
    "OrderItem",      # Depends on: Order, Product2, PricebookEntry
    "Case",           # Depends on: Account, Contact, User, Issue__c, OrderItem (optional)
    "Task",           # Depends on: Account, Contact, Lead, Opportunity, Case (all optional via WhoId/WhatId)
    "Event",          # Depends on: Account, Contact, Lead, Opportunity (all optional via WhoId/WhatId)
    "ProductCategoryProduct", # Depends on: ProductCategory, Product2
    "EmailMessage",   # Depends on: Case (ParentId)
    "LiveChatTranscript", # Depends on: Account, Case, Contact, User, Lead
    "VoiceCallTranscript__c", # Depends on: Case (optional), Contact (optional), User (optional)
    "CaseHistory__c", # Depends on: Case, User
    "Knowledge__kav", # No dependencies (but requires Knowledge to be enabled)
]

class DataUploader:
    def __init__(self, org_type: str = "original", dry_run: bool = False):
        """Initialize the data uploader."""
        # Load .env from parent directory (CRMArena root) or current directory
        env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
        if os.path.exists(env_path):
            load_dotenv(env_path)
        else:
            load_dotenv()  # Fallback to default search
        self.org_type = org_type
        self.dry_run = dry_run
        
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
            except Exception as e:
                error_msg = str(e)
                if "INVALID_LOGIN" in error_msg or "INVALID_CREDENTIALS" in error_msg:
                    print(f"⚠️  Username/password authentication failed: {error_msg}")
                    print("   Trying access token method (for scratch orgs)...")
                    
                    # Try access token method (for scratch orgs)
                    try:
                        access_token, instance_url = self._get_access_token_from_cli()
                        if access_token and instance_url:
                            self.sf = Salesforce(instance_url=instance_url, session_id=access_token)
                            print("✅ Connected using access token from Salesforce CLI!")
                        else:
                            raise ValueError("Could not get access token from CLI")
                    except Exception as e2:
                        print(f"❌ Access token method also failed: {e2}")
                        print("\n💡 Solutions:")
                        print("   1. Reset security token in Salesforce UI:")
                        print("      - Open org: sf org open --target-org <your-org-alias>")
                        print("      - Go to: Setup → My Personal Information → Reset My Security Token")
                        print("   2. Or make sure Salesforce CLI is authenticated: sf org list")
                        raise ValueError(f"Authentication failed. See solutions above.")
                else:
                    raise
        else:
            # Try access token method if credentials not provided
            print("   No username/password provided, trying access token method...")
            try:
                access_token, instance_url = self._get_access_token_from_cli()
                if access_token and instance_url:
                    self.sf = Salesforce(instance_url=instance_url, session_id=access_token)
                    print("✅ Connected using access token from Salesforce CLI!")
                else:
                    raise ValueError("Could not get access token from CLI")
            except Exception as e:
                raise ValueError(f"Missing credentials and access token method failed: {e}")

        # Debug counters to avoid spamming logs
        self._debug_orderitem_lookup_logged = False
        
        # ID mapping database (persistent SQLite storage)
        self.id_mapping_db = IdMappingDB()
        mapping_count = self.id_mapping_db.get_count()
        if mapping_count > 0:
            print(f"  📦 Loaded {mapping_count} existing ID mappings from database")
        
        # Legacy in-memory mapping (kept for compatibility, but uses DB under the hood)
        self.id_mapping = {}  # {object_name: {old_id: new_id}}
        
        # Database connection
        # Database path (relative to CRMArena root or etl folder)
        # Use different database files based on org_type
        if org_type == "b2b":
            db_filename = "crmarenapro_b2b_data.db"
        elif org_type == "b2c":
            db_filename = "crmarenapro_b2c_data.db"
        else:  # original
            db_filename = "crmarena_data.db"
        
        db_path = f"../local_data/{db_filename}"
        if not os.path.exists(db_path):
            # Try from CRMArena root (if running from there)
            db_path = f"local_data/{db_filename}"
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Database not found: {db_path} (org_type: {org_type})")
        
        print(f"  📂 Using database: {db_path}")
        self.db = sqlite3.connect(db_path)
        
        if dry_run:
            print("🔍 DRY RUN MODE - No data will be uploaded\n")
    
    def _get_access_token_from_cli(self):
        """Get access token from Salesforce CLI for scratch orgs."""
        
        # Method 1: Try the default target-org first
        try:
            result = subprocess.run(
                ['sf', 'config', 'get', 'target-org', '--json'],
                capture_output=True,
                text=True,
                check=True
            )
            config_data = json.loads(result.stdout)
            default_org = None
            result_list = config_data.get('result', [])
            if isinstance(result_list, list) and len(result_list) > 0:
                default_org = result_list[0].get('value', '')
            
            if default_org:
                result2 = subprocess.run(
                    ['sf', 'org', 'display', '--target-org', default_org, '--json'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                data = json.loads(result2.stdout)
                access_token = data.get('result', {}).get('accessToken', '')
                instance_url = data.get('result', {}).get('instanceUrl', '')
                if access_token and instance_url:
                    print(f"   Using default target-org: {default_org}")
                    return access_token, instance_url
        except Exception as e:
            pass
        
        # Method 2: Try to find scratch org matching the username in .env
        try:
            username = os.getenv("SALESFORCE_USERNAME", "")
            if username:
                result = subprocess.run(
                    ['sf', 'org', 'list', '--json'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                data = json.loads(result.stdout)
                # Find org matching username
                all_orgs = data.get('result', {}).get('nonScratchOrgs', []) + data.get('result', {}).get('scratchOrgs', [])
                for org in all_orgs:
                    org_username = org.get('username', '')
                    if org_username == username or (username.split('@')[0] in org_username):
                        alias = org.get('alias', org_username)
                        result2 = subprocess.run(
                            ['sf', 'org', 'display', '--target-org', alias, '--json'],
                            capture_output=True,
                            text=True,
                            check=True
                        )
                        data2 = json.loads(result2.stdout)
                        access_token = data2.get('result', {}).get('accessToken', '')
                        instance_url = data2.get('result', {}).get('instanceUrl', '')
                        if access_token and instance_url:
                            print(f"   Found matching org: {alias}")
                            return access_token, instance_url
        except Exception as e:
            pass
        
        # Method 3: Try any available scratch org
        try:
            result = subprocess.run(
                ['sf', 'org', 'list', '--json'],
                capture_output=True,
                text=True,
                check=True
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
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    data2 = json.loads(result2.stdout)
                    access_token = data2.get('result', {}).get('accessToken', '')
                    instance_url = data2.get('result', {}).get('instanceUrl', '')
                    if access_token and instance_url:
                        print(f"   Using scratch org: {alias}")
                        return access_token, instance_url
        except Exception as e:
            pass
        
        return None, None
    
    def get_table_data(self, table_name: str) -> pd.DataFrame:
        """Get all data from a table."""
        query = f'SELECT * FROM "{table_name}"'
        df = pd.read_sql_query(query, self.db)
        return df
    
    def clean_field_value(self, value, field_name: str = "", object_name: str = "") -> any:
        """Clean and convert field values for Salesforce."""
        if pd.isna(value) or value is None:
            return None
        
        # Handle boolean fields (IsActive, etc.)
        if field_name in ["IsActive"] or field_name.startswith("Is"):
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            value_str = str(value).lower()
            return value_str in ["true", "1", "yes"]
        
        # Handle numeric fields
        if isinstance(value, (int, float)):
            # If it's already numeric, return as-is (but convert int to float for some fields)
            return value
        
        # Convert to string for other processing
        value_str = str(value)
        
        # Handle empty strings
        if value_str.strip() == "":
            return None
        
        # Handle date/datetime fields
        if "Date" in field_name or "Time" in field_name:
            # Try to parse common date formats
            try:
                from datetime import datetime
                # Handle ISO format
                if "T" in value_str:
                    dt = datetime.fromisoformat(value_str.replace("Z", "+00:00"))
                    return dt.isoformat()
                # Handle date-only format
                if len(value_str) == 10 and "-" in value_str:
                    return value_str
                return value_str
            except:
                return value_str
        
        # Default: return as string
        return value_str
    
    def _load_existing_ids(self):
        """Load IDs of records already in Salesforce to build mapping."""
        # For now, we'll build mapping as we upload
        # In future, could query Salesforce for existing External_ID__c fields
        pass
    
    def _create_livechat_visitors_from_ids(self, visitor_ids):
        """
        Create LiveChatVisitor records for a list of unique LiveChatVisitorIds.
        LiveChatVisitor records must exist before LiveChatTranscript can be uploaded.
        """
        print(f"\n{'='*60}")
        print("Creating LiveChatVisitor Records")
        print(f"{'='*60}\n")
        
        print(f"Found {len(visitor_ids)} unique LiveChatVisitorIds to create")
        
        if not visitor_ids:
            print(f"⚠️  No LiveChatVisitorIds found")
            return
        
        # Create LiveChatVisitor records (they have no required fields!)
        created = 0
        errors = 0
        
        for old_visitor_id in visitor_ids:
            try:
                # Check if already mapped
                existing_mapping = self.id_mapping_db.get_mapping("LiveChatVisitor", old_visitor_id)
                if existing_mapping:
                    continue  # Already exists, skip silently
                
                # Create empty LiveChatVisitor (no required fields)
                result = self.sf.LiveChatVisitor.create({})
                new_visitor_id = result['id']
                
                # Save mapping
                self.id_mapping_db.save_mapping("LiveChatVisitor", old_visitor_id, new_visitor_id)
                created += 1
                
                if created % 10 == 0:
                    print(f"  Progress: {created} LiveChatVisitors created...")
                
            except Exception as e:
                errors += 1
                if errors < 5:
                    print(f"  ❌ Error creating LiveChatVisitor: {str(e)[:100]}")
        
        print(f"\n✅ Created {created} new LiveChatVisitor records")
        if errors > 0:
            print(f"❌ Errors: {errors}")
        print(f"ℹ️  LiveChatTranscript records can now reference these visitors\n")
    
    def _create_livechat_visitors_for_transcripts(self, transcript_records):
        """
        Create LiveChatVisitor records for all unique LiveChatVisitorIds in LiveChatTranscript records.
        LiveChatVisitor records must exist before LiveChatTranscript can be uploaded.
        """
        print(f"\n{'='*60}")
        print("Creating LiveChatVisitor Records")
        print(f"{'='*60}\n")
        
        # Extract unique LiveChatVisitorIds from transcript records
        visitor_ids = set()
        for record in transcript_records:
            if "LiveChatVisitorId" in record and record["LiveChatVisitorId"]:
                visitor_ids.add(record["LiveChatVisitorId"])
        
        print(f"Found {len(visitor_ids)} unique LiveChatVisitorIds to create")
        
        if not visitor_ids:
            print(f"⚠️  No LiveChatVisitorIds found in records")
            return
        
        # Create LiveChatVisitor records (they have no required fields!)
        created = 0
        errors = 0
        
        for old_visitor_id in visitor_ids:
            try:
                # Check if already mapped
                existing_mapping = self.id_mapping_db.get_mapping("LiveChatVisitor", old_visitor_id)
                if existing_mapping:
                    print(f"  ℹ️  LiveChatVisitor {old_visitor_id[:15]}... already mapped to {existing_mapping[:15]}...")
                    continue
                
                # Create empty LiveChatVisitor (no required fields)
                result = self.sf.LiveChatVisitor.create({})
                new_visitor_id = result['id']
                
                # Save mapping
                self.id_mapping_db.save_mapping("LiveChatVisitor", old_visitor_id, new_visitor_id)
                created += 1
                
                if created % 10 == 0:
                    print(f"  Progress: {created} LiveChatVisitors created...")
                
            except Exception as e:
                errors += 1
                if errors < 5:
                    print(f"  ❌ Error creating LiveChatVisitor: {str(e)[:100]}")
        
        print(f"\n✅ Created {created} LiveChatVisitor records")
        if errors > 0:
            print(f"❌ Errors: {errors}")
        print(f"ℹ️  LiveChatTranscript records can now reference these visitors\n")
    
    def map_id(self, old_id: str, object_name: str) -> Optional[str]:
        """Map old ID to new Salesforce ID using persistent database."""
        if not old_id or pd.isna(old_id):
            return None
        
        # Use the persistent ID mapping database
        return self.id_mapping_db.get_mapping(object_name, str(old_id))
    
    def _ensure_standard_pricebook_entries(self, df: pd.DataFrame):
        """Pre-create standard pricebook entries in bulk for all products in the dataframe."""
        try:
            # Get standard pricebook ID
            standard_pb_query = "SELECT Id FROM Pricebook2 WHERE IsStandard = true LIMIT 1"
            standard_pb_result = self.sf.query(standard_pb_query)
            if not standard_pb_result['records']:
                print("  ⚠️  No standard pricebook found")
                return
            standard_pb_id = standard_pb_result['records'][0]['Id']
            
            # Get all unique Product2Ids that need standard pricebook entries
            # (entries for non-standard pricebooks require standard pricebook entries first)
            product_ids_needed = set()
            for _, row in df.iterrows():
                product_id_raw = row.get('Product2Id')
                pricebook_id_raw = row.get('Pricebook2Id')
                
                # Map the IDs
                product_id = self.map_id(product_id_raw, 'Product2') if product_id_raw else None
                pricebook_id = self.map_id(pricebook_id_raw, 'Pricebook2') if pricebook_id_raw else None
                
                # Only need standard entry if targeting a non-standard pricebook
                if product_id and pricebook_id and pricebook_id != standard_pb_id:
                    product_ids_needed.add(product_id)
            
            if not product_ids_needed:
                return
            
            print(f"  ℹ️  Checking {len(product_ids_needed)} products for standard pricebook entries...")
            
            # Query which products already have standard pricebook entries
            existing_products = set()
            product_ids_list = list(product_ids_needed)
            # Query in batches of 200 to avoid SOQL limits
            for i in range(0, len(product_ids_list), 200):
                batch = product_ids_list[i:i+200]
                ids_str = "','".join(batch)
                query = f"SELECT Product2Id FROM PricebookEntry WHERE Pricebook2Id = '{standard_pb_id}' AND Product2Id IN ('{ids_str}')"
                try:
                    result = self.sf.query(query)
                    for rec in result.get('records', []):
                        existing_products.add(rec['Product2Id'])
                except:
                    pass
            
            # Create missing standard pricebook entries in bulk
            products_to_create = product_ids_needed - existing_products
            if not products_to_create:
                print(f"  ✅ All {len(product_ids_needed)} products already have standard pricebook entries")
                return
            
            print(f"  📥 Creating {len(products_to_create)} standard pricebook entries in bulk...")
            
            # Build records for bulk insert
            std_entries = []
            for product_id in products_to_create:
                std_entries.append({
                    "Pricebook2Id": standard_pb_id,
                    "Product2Id": product_id,
                    "UnitPrice": 0,  # Default price
                    "IsActive": True
                })
            
            # Bulk insert (serial mode to avoid lock errors)
            try:
                results = self.sf.bulk.PricebookEntry.insert(std_entries, batch_size=1000, use_serial=True)
                success_count = sum(1 for r in results if r.get('success'))
                error_count = len(results) - success_count
                print(f"  ✅ Created {success_count} standard pricebook entries ({error_count} errors)")
            except Exception as e:
                print(f"  ⚠️  Bulk create failed, trying one-by-one: {str(e)[:50]}")
                # Fallback to individual creates
                success_count = 0
                for entry in std_entries[:100]:  # Limit fallback to first 100
                    try:
                        self.sf.PricebookEntry.create(entry)
                        success_count += 1
                    except:
                        pass
                print(f"  ✅ Created {success_count} standard pricebook entries (fallback)")
                
        except Exception as e:
            print(f"  ⚠️  Could not pre-create standard pricebook entries: {str(e)[:100]}")
    
    def _ensure_pricebook_entries_for_orders(self):
        """
        Ensure PricebookEntries exist for all Products referenced by uploaded Orders.
        This is needed before OrderItems can be uploaded.
        Queries the source database to find all Product-Pricebook combinations needed.
        """
        print(f"\n{'='*60}")
        print("Ensuring PricebookEntries for OrderItems")
        print(f"{'='*60}\n")
        
        try:
            # Query source database for Product-Pricebook combinations needed
            cursor = self.db.cursor()
            
            query = """
                SELECT DISTINCT 
                    o.Pricebook2Id as OrderPricebook,
                    oi.Product2Id,
                    oi.UnitPrice
                FROM "Order" o
                JOIN OrderItem oi ON o.Id = oi.OrderId
            """
            cursor.execute(query)
            entries_needed = cursor.fetchall()
            
            print(f"Found {len(entries_needed)} Product-Pricebook combinations needed for OrderItems")
            
            if not entries_needed:
                print("  ℹ️  No OrderItems found in source database")
                return
            
            # Process each combination
            created = 0
            skipped = 0
            already_exists = 0
            
            for old_pricebook_id, old_product_id, unit_price in entries_needed:
                # Map old IDs to new Salesforce IDs
                new_pricebook_id = self.id_mapping_db.get_mapping("Pricebook2", old_pricebook_id)
                new_product_id = self.id_mapping_db.get_mapping("Product2", old_product_id)
                
                if not new_pricebook_id or not new_product_id:
                    skipped += 1
                    continue
                
                # Check if PricebookEntry already exists
                try:
                    check_query = f"SELECT Id FROM PricebookEntry WHERE Pricebook2Id = '{new_pricebook_id}' AND Product2Id = '{new_product_id}' LIMIT 1"
                    result = self.sf.query(check_query)
                    
                    if result.get('records'):
                        already_exists += 1
                        continue
                    
                    # Create the PricebookEntry
                    new_pbe = {
                        'Pricebook2Id': new_pricebook_id,
                        'Product2Id': new_product_id,
                        'UnitPrice': float(unit_price) if unit_price else 100.00,
                        'IsActive': True
                    }
                    pbe_result = self.sf.PricebookEntry.create(new_pbe)
                    created += 1
                    
                    if created % 50 == 0:
                        print(f"  Progress: Created {created} PricebookEntries...")
                        
                except Exception as e:
                    error_str = str(e)
                    if "DUPLICATE_VALUE" in error_str:
                        already_exists += 1
                    elif "STANDARD_PRICE_NOT_DEFINED" in error_str:
                        # Need to create standard pricebook entry first
                        try:
                            # Get standard pricebook
                            std_pb_query = "SELECT Id FROM Pricebook2 WHERE IsStandard = true LIMIT 1"
                            std_pb_result = self.sf.query(std_pb_query)
                            if std_pb_result.get('records'):
                                std_pb_id = std_pb_result['records'][0]['Id']
                                
                                # Create standard entry first
                                std_entry = {
                                    'Pricebook2Id': std_pb_id,
                                    'Product2Id': new_product_id,
                                    'UnitPrice': float(unit_price) if unit_price else 100.00,
                                    'IsActive': True
                                }
                                self.sf.PricebookEntry.create(std_entry)
                                
                                # Now create the custom pricebook entry
                                self.sf.PricebookEntry.create(new_pbe)
                                created += 1
                        except:
                            skipped += 1
                    else:
                        skipped += 1
                        if created == 0 and skipped <= 3:
                            print(f"  ⚠️  Warning: {error_str[:100]}")
            
            print(f"\n✅ PricebookEntry Summary:")
            print(f"  Created: {created}")
            print(f"  Already existed: {already_exists}")
            if skipped > 0:
                print(f"  Skipped: {skipped} (unmapped IDs or errors)")
            
        except Exception as e:
            print(f"❌ Error ensuring PricebookEntries: {str(e)[:200]}")
    
    def upload_object(self, object_name: str, limit: Optional[int] = None) -> Dict:
        """Upload records for an object."""
        print(f"\n📤 Uploading {object_name}...")
        
        # Get data from database
        df = self.get_table_data(object_name)
        
        if len(df) == 0:
            print(f"  ℹ️  No records found for {object_name}")
            return {"uploaded": 0, "skipped": 0, "errors": 0}
        
        if limit:
            df = df.head(limit)
            print(f"  ℹ️  Limiting to {limit} records")
        
        print(f"  Found {len(df)} records")
        
        # For LiveChatTranscript: Create LiveChatVisitor records FIRST (before any record processing)
        if object_name == "LiveChatTranscript" and "LiveChatVisitorId" in df.columns:
            unique_visitor_ids = df["LiveChatVisitorId"].dropna().unique().tolist()
            if unique_visitor_ids:
                self._create_livechat_visitors_from_ids(unique_visitor_ids)
        
        if self.dry_run:
            print(f"  [DRY RUN] Would upload {len(df)} records to {object_name}")
            # Show sample record
            if len(df) > 0:
                print(f"  Sample record: {df.iloc[0].to_dict()}")
            return {"uploaded": len(df), "skipped": 0, "errors": 0}
        
        # Prepare records for upload
        records = []
        old_ids = []  # Store old IDs in order - matches records list (only valid records)
        record_indices = []  # Track which original row index each record came from

        # Special: OrderItem has incorrect field name in source database
        if object_name == "OrderItem" and "PriceBookEntryId" in df.columns:
            df = df.rename(columns={"PriceBookEntryId": "PricebookEntryId"})
            print(f"  ℹ️  Renamed PriceBookEntryId column to PricebookEntryId")

        # For Contact, pre-load existing emails to avoid DUPLICATES_DETECTED errors
        # Note: we no longer skip Contacts with duplicate emails; we want full dataset.
        # Duplicate rules in the org will govern behavior if enabled.
        existing_contact_emails: Set[str] = set()
        batch_contact_emails: Set[str] = set()
        
        # For PricebookEntry: pre-create standard pricebook entries in bulk
        if object_name == "PricebookEntry":
            self._ensure_standard_pricebook_entries(df)
        
        for idx, row in df.iterrows():
            # Store old ID first (will be added to list only if record is valid)
            old_id = row['Id'] if 'Id' in df.columns else None
            
            record = {}
            phone_value = None  # Store phone for Account Name generation
            email_value = None  # Store email for Contact duplicate detection
            
            # Add OriginalId__c for upsert support (External ID)
            # Skip for Knowledge__kav which uses UrlName instead
            if old_id and not pd.isna(old_id) and object_name != "Knowledge__kav":
                record['OriginalId__c'] = str(old_id)
            
            for col in df.columns:
                if col == "Id":
                    # Don't include old ID as 'Id' field (Salesforce will generate new one)
                    # We use OriginalId__c instead for upsert matching
                    continue
                
                value = row[col]
                
                # Skip fields that don't exist in standard Salesforce setup
                # Account: RecordTypeId and FirstName/LastName are for Person Accounts only
                if object_name == "Account":
                    if col in ["RecordTypeId", "FirstName", "LastName", "PersonEmail"]:
                        # Skip Person Account fields (not available in standard setup)
                        continue
                    # ShippingState/ShippingCity might cause validation issues - skip for now
                    if col in ["ShippingState", "ShippingCity"]:
                        continue
                    # Store phone for Name generation
                    if col == "Phone":
                        phone_value = value

                # Case: skip IssueId__c if the field doesn't exist in the org
                if object_name == "Case" and col == "IssueId__c":
                    continue

                # Contact: store Email for duplicate detection
                if object_name == "Contact" and col == "Email":
                    email_value = value
                
                # EmailMessage: ToIds field causes issues - skip for now
                # ToIds might need special handling or might not be settable via API
                if object_name == "EmailMessage" and col == "ToIds":
                    continue
                
                # Skip custom fields that might not exist
                # For now, skip External_ID__c if it causes issues (can be added later)
                if col == "External_ID__c":
                    # Skip for now - field might not exist in org
                    continue
                
                # Knowledge__kav: Skip FAQ_Answer__c if it doesn't exist
                if object_name == "Knowledge__kav" and col == "FAQ_Answer__c":
                    # FAQ_Answer__c is a custom field that may not exist
                    # Skip it - Knowledge articles can be created without it
                    continue
                
                # Skip CaseHistory__c custom fields that might not exist
                if object_name == "CaseHistory__c":
                    if col in ["Field__c", "NewValue__c", "OldValue__c", "CaseId__c"]:
                        # Skip custom fields that don't exist
                        continue
                
                # Skip system audit fields that can't be set via API (for all objects)
                if col in ["CreatedDate", "LastModifiedDate", "SystemModstamp"]:
                    # These are read-only system fields - Salesforce will set them automatically
                    continue
                
                # Case-specific: also skip ClosedDate
                if object_name == "Case":
                    if col == "ClosedDate":
                        # ClosedDate is read-only - Salesforce will set it automatically
                        continue
                
                # Skip fields that don't exist in standard objects
                if object_name == "Pricebook2":
                    if col in ["ValidFrom", "ValidTo"]:
                        # These fields might not exist in standard Pricebook2
                        continue
                
                if object_name == "ProductCategory":
                    if col == "CatalogId":
                        # CatalogId is required - we'll need to create a default or skip
                        # For now, skip ProductCategory records that require CatalogId
                        # This will be handled in special handling below
                        pass
                
                # Map lookup/reference fields
                if col.endswith("Id") or col.endswith("Id__c"):
                    # Determine referenced object
                    ref_obj = self._get_referenced_object(col, object_name)
                    
                    # Handle polymorphic fields (WhatId, WhoId) by detecting object from ID prefix
                    if ref_obj == "Polymorphic" and value and not pd.isna(value):
                        # Detect object type from ID prefix
                        id_str = str(value)
                        if id_str.startswith("006"):  # Opportunity
                            ref_obj = "Opportunity"
                        elif id_str.startswith("001"):  # Account
                            ref_obj = "Account"
                        elif id_str.startswith("500"):  # Case
                            ref_obj = "Case"
                        elif id_str.startswith("00Q"):  # Lead
                            ref_obj = "Lead"
                        elif id_str.startswith("003"):  # Contact
                            ref_obj = "Contact"
                        elif id_str.startswith("800"):  # Contract
                            ref_obj = "Contract"
                        else:
                            # Unknown object type - skip this field
                            ref_obj = None
                    
                    if ref_obj:
                        mapped_id = self.map_id(value, ref_obj)
                        if mapped_id:
                            record[col] = mapped_id
                        elif value and not pd.isna(value):
                            # ID not mapped yet - might be a dependency issue
                            # For User references, we can skip since User is not uploaded
                            if ref_obj == "User":
                                # For Task/Event, OwnerId is REQUIRED - use current authenticated user
                                if object_name in ["Task", "Event"] and col == "OwnerId":
                                    # Get current user ID if not already cached
                                    if not hasattr(self, '_current_user_id'):
                                        try:
                                            # Query for current authenticated user
                                            user_result = self.sf.query("SELECT Id FROM User WHERE IsActive = true LIMIT 1")
                                            self._current_user_id = user_result['records'][0]['Id']
                                        except Exception as e:
                                            print(f"    ⚠️  Warning: Could not get current user ID: {e}")
                                            continue
                                    record[col] = self._current_user_id
                                else:
                                    # Skip OwnerId if User not uploaded (for other objects)
                                    continue
                            elif ref_obj == "Account" and object_name == "Contact":
                                # For Contact, AccountId is optional - skip if not mapped
                                # This allows Contacts to be uploaded without Account
                                print(f"    ⚠️  Warning: {col} references {ref_obj} but ID {value} not found in mapping - skipping field")
                                continue
                            elif ref_obj == "OrderItem" and object_name == "Case":
                                # For Case, OrderItemId__c is optional - skip if not mapped
                                # OrderItem might not be uploaded yet or might not exist
                                # Skip silently (no warning) since this is expected
                                continue
                            elif ref_obj == "PricebookEntry" and object_name == "OrderItem":
                                # For OrderItem, PricebookEntryId is required but might not be mapped yet
                                # Skip silently if not mapped (will be caught by required field check)
                                if not self._debug_orderitem_lookup_logged:
                                    existing_pbe = self.id_mapping_db.get_count("PricebookEntry")
                                    print(f"    🔍 Debug: PricebookEntryId {value} not mapped. "
                                          f"Current PricebookEntry mappings: {existing_pbe}")
                                continue
                            elif ref_obj == "Order" and object_name == "OrderItem":
                                # For OrderItem, OrderId is required - log debug info on first failure
                                if not self._debug_orderitem_lookup_logged:
                                    existing_orders = self.id_mapping_db.get_count("Order")
                                    sample_mappings = list(self.id_mapping_db.get_all_for_object("Order").items())[:5]
                                    print(f"    🔍 Debug: OrderId {value} not mapped.")
                                    print(f"       Order mappings count: {existing_orders}")
                                    if sample_mappings:
                                        print(f"       Sample Order mappings (old -> new): "
                                              f"{', '.join([f'{o}->{n}' for o, n in sample_mappings])}")
                                    self._debug_orderitem_lookup_logged = True
                                continue
                            elif ref_obj == "Case" and object_name == "EmailMessage":
                                # For EmailMessage, ParentId (Case) is optional - allow NULL
                                # Keep the field as-is (NULL or mapped)
                                pass
                            elif ref_obj == "ProductCategory" and object_name == "ProductCategoryProduct":
                                # For ProductCategoryProduct, ProductCategoryId is required
                                # Log which ProductCategoryId is missing to help debug
                                print(f"    ⚠️  Warning: {col} references {ref_obj} but ID {value} not found in mapping")
                                print(f"       This may indicate ProductCategory records failed to upload (check CatalogId requirements)")
                                # Don't include the field if ID can't be mapped
                                continue
                            else:
                                # For other objects, try to find by querying Salesforce
                                # For now, just skip the field and warn
                                print(f"    ⚠️  Warning: {col} references {ref_obj} but ID {value} not found in mapping")
                                # Don't include the field if ID can't be mapped
                                continue
                    else:
                        # Not a lookup field, include as-is
                        record[col] = self.clean_field_value(value, col, object_name)
                else:
                    record[col] = self.clean_field_value(value, col, object_name)
            
            # Special handling: Account requires Name field
            if object_name == "Account" and "Name" not in record:
                # Generate Name from available data or use a default
                if phone_value and not pd.isna(phone_value):
                    record["Name"] = f"Account-{phone_value}"
                else:
                    # Use ID as fallback
                    record["Name"] = f"Account-{old_id[:8]}" if old_id else "Account"
            
            # For Contact, we keep all records even if emails repeat.
            # Duplicate rules (if any) in the org will control behavior.

            # Remove None values (Salesforce doesn't like them in some cases)
            record = {k: v for k, v in record.items() if v is not None}
            
            # Check for required fields that are missing
            # Order requires AccountId
            if object_name == "Order" and "AccountId" not in record:
                print(f"    ⚠️  Skipping Order record - AccountId is required but not mapped")
                continue
            
            # PricebookEntry requires Pricebook2Id and Product2Id
            if object_name == "PricebookEntry":
                if "Pricebook2Id" not in record or "Product2Id" not in record:
                    print(f"    ⚠️  Skipping PricebookEntry record - Pricebook2Id and Product2Id are required but not mapped")
                    continue
                # IMPORTANT: PricebookEntry records are inactive by default - must set IsActive = True
                if "IsActive" not in record:
                    record["IsActive"] = True
            
            # OrderItem requires OrderId and PricebookEntryId
            # Note: These are checked and mapped earlier in the ID mapping logic (lines 731-799)
            # If they're missing after mapping, Salesforce will reject them with proper error messages
            # No need for premature validation here
            
            # ProductCategoryProduct requires ProductCategoryId and ProductId
            if object_name == "ProductCategoryProduct":
                if "ProductCategoryId" not in record or "ProductId" not in record:
                    print(f"    ⚠️  Skipping ProductCategoryProduct record - ProductCategoryId and ProductId are required but not mapped")
                    continue
            
            # EmailMessage ParentId is optional (contrary to previous assumption)
            # EmailMessages without ParentId can still be uploaded with Enhanced Email enabled
            
            # Only add to records if we got here (record is valid)
            records.append(record)
            old_ids.append(old_id)  # Store old ID for this valid record
            record_indices.append(idx)  # Store original row index
        
        if not records:
            print(f"  ⚠️  No valid records to upload after processing")
            return {"uploaded": 0, "skipped": 0, "errors": 0}
        
        # Special handling for User object
        if object_name == "User":
            # User creation requires additional fields and permissions
            # Try to get a default ProfileId if not provided
            default_profile_id = None
            try:
                # Query for Standard User or System Administrator profile
                profile_query = "SELECT Id FROM Profile WHERE Name IN ('Standard User', 'System Administrator') LIMIT 1"
                profile_result = self.sf.query(profile_query)
                if profile_result['records']:
                    default_profile_id = profile_result['records'][0]['Id']
                    print(f"  ℹ️  Using default Profile: {default_profile_id}")
            except Exception as e:
                print(f"  ⚠️  Could not query for Profile: {e}")
            
            # Load existing usernames to avoid duplicates
            existing_usernames = set()
            try:
                print(f"  ℹ️  Loading existing User usernames to avoid duplicates...")
                user_query = "SELECT Username FROM User WHERE Username != NULL"
                user_result = self.sf.query(user_query)
                existing_usernames = {r['Username'].lower() for r in user_result['records']}
                print(f"  ℹ️  Found {len(existing_usernames)} existing User usernames")
            except Exception as e:
                print(f"  ⚠️  Could not query existing usernames: {e}")
                print(f"     Will attempt upload and handle duplicates as they occur")
            
            # Add required fields to each User record
            valid_records = []
            for record in records:
                # Validate email format if Email is provided
                email = record.get("Email")
                if email:
                    # Basic email validation - must contain @ and valid domain with TLD
                    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                    if not re.match(email_pattern, email):
                        # Check if it looks like an org ID pattern (email@15+ alphanumeric chars, no dot)
                        if '@' in email:
                            domain = email.split('@')[1]
                            if re.match(r'^[0-9A-Za-z]{15,}$', domain) and '.' not in domain:
                                # Looks like an org ID or similar - likely invalid
                                print(f"    ⚠️  Skipping User - invalid email format (looks like org ID): {email}")
                            else:
                                print(f"    ⚠️  Skipping User - invalid email address: {email}")
                        else:
                            print(f"    ⚠️  Skipping User - invalid email address: {email}")
                        continue
                
                # Username is required - use Email if Username not provided
                if "Username" not in record or not record.get("Username"):
                    if email:
                        record["Username"] = email
                    else:
                        print(f"    ⚠️  Skipping User - Username/Email required")
                        continue
                
                # Check for duplicate username
                username = record.get("Username", "").lower()
                if username in existing_usernames:
                    print(f"    ⚠️  Skipping User with duplicate Username: {record.get('Username')}")
                    continue
                
                # LastName is required
                if "LastName" not in record or not record.get("LastName"):
                    if "FirstName" in record and record.get("FirstName"):
                        record["LastName"] = record["FirstName"]  # Use FirstName as fallback
                    else:
                        record["LastName"] = "User"  # Default fallback
                
                # Alias is required (max 8 chars)
                if "Alias" not in record or not record.get("Alias"):
                    # Generate from Username or LastName
                    if "Username" in record:
                        alias = record["Username"].split("@")[0][:8]
                    elif "LastName" in record:
                        alias = record["LastName"][:8]
                    else:
                        alias = "user"
                    record["Alias"] = alias
                
                # ProfileId is required
                if "ProfileId" not in record or not record.get("ProfileId"):
                    if default_profile_id:
                        record["ProfileId"] = default_profile_id
                    else:
                        print(f"    ⚠️  Skipping User {record.get('Username', 'unknown')} - ProfileId required")
                        continue
                
                # Set default values for required fields if not present
                if "TimeZoneSidKey" not in record:
                    record["TimeZoneSidKey"] = "America/New_York"
                if "LocaleSidKey" not in record:
                    record["LocaleSidKey"] = "en_US"
                if "EmailEncodingKey" not in record:
                    record["EmailEncodingKey"] = "UTF-8"
                if "LanguageLocaleKey" not in record:
                    record["LanguageLocaleKey"] = "en_US"
                
                # Add to valid records
                valid_records.append(record)
                # Track this username to avoid duplicates in the same batch
                existing_usernames.add(username)
            
            # Use valid records
            records = valid_records
            
            if not records:
                print(f"  ⚠️  No valid User records after processing")
                return {"uploaded": 0, "skipped": 0, "errors": 0}
            
            print(f"  ℹ️  Attempting to create {len(records)} User(s) (requires 'Manage Users' permission)")
            print(f"     If you get permission errors, see ENABLE_USER_CREATION.md for setup instructions")
        
        # Special handling for Knowledge__kav - UrlName must be unique and Language is required
        if object_name == "Knowledge__kav":
            # Load existing UrlNames to avoid duplicates (query ALL versions including draft/archived)
            existing_urlnames = set()
            try:
                print(f"  ℹ️  Loading existing Knowledge article UrlNames to avoid duplicates...")
                # Query all versions: Draft, Online (published), and Archived
                for publish_status in ['Draft', 'Online', 'Archived']:
                    try:
                        urlname_query = f"SELECT UrlName FROM Knowledge__kav WHERE PublishStatus = '{publish_status}' AND UrlName != NULL"
                        urlname_result = self.sf.query(urlname_query)
                        for r in urlname_result['records']:
                            if r.get('UrlName'):
                                existing_urlnames.add(r['UrlName'].lower())
                    except:
                        pass  # Some statuses might not be accessible
                print(f"  ℹ️  Found {len(existing_urlnames)} existing Knowledge article UrlNames")
            except Exception as e:
                print(f"  ⚠️  Could not query existing UrlNames: {e}")
            
            # Make UrlNames unique and add required fields
            valid_records = []
            for record in records:
                # Add required Language field if missing
                if "Language" not in record or not record.get("Language"):
                    record["Language"] = "en_US"
                
                # Add ValidationStatus if missing (helps with publishing)
                if "ValidationStatus" not in record or not record.get("ValidationStatus"):
                    record["ValidationStatus"] = "Draft"
                
                if "UrlName" in record and record.get("UrlName"):
                    urlname = record["UrlName"].lower()
                    if urlname in existing_urlnames:
                        # Make it unique by appending a suffix
                        import time
                        suffix = f"-{int(time.time()) % 10000}"
                        record["UrlName"] = record["UrlName"] + suffix
                        print(f"    ℹ️  Modified UrlName to avoid duplicate: {record['UrlName']}")
                    existing_urlnames.add(record["UrlName"].lower())
                valid_records.append(record)
            records = valid_records
            print(f"  ℹ️  Added Language='en_US' and ValidationStatus='Draft' to {len(records)} Knowledge articles")
        
        # Special handling for LiveChatTranscript - check if Live Agent is enabled
        if object_name == "LiveChatTranscript":
            # Check if LiveChatTranscript object exists (Live Agent must be enabled)
            try:
                test_query = "SELECT Id FROM LiveChatTranscript LIMIT 1"
                self.sf.query(test_query)
                print(f"  ℹ️  Live Agent appears to be enabled - proceeding with upload")
            except Exception as e:
                error_str = str(e)
                if 'ENTITY_NOT_FOUND' in error_str or 'INVALID_TYPE' in error_str or 'Unable to find object' in error_str:
                    print(f"  ℹ️  LiveChatTranscript skipped (expected): Live Agent is not enabled in this org")
                    print(f"     This is normal - LiveChatTranscript requires Live Agent feature to be enabled")
                    print(f"     Other objects will continue to upload normally")
                    print(f"     To enable: Setup → Live Agent → Settings → Enable Live Agent")
                    return {"uploaded": 0, "skipped": len(records), "errors": 0}
                else:
                    # Other error - might be permissions, try to proceed
                    print(f"  ⚠️  Warning: Could not verify Live Agent status: {error_str[:100]}")
                    print(f"     Attempting upload anyway...")
        
        # Special handling for Lead - remove read-only conversion fields and IsConverted flag
        if object_name == "Lead":
            # Remove conversion fields (read-only, set only when Lead is converted)
            # Also remove IsConverted flag - Leads in new org should not be marked as converted
            readonly_fields = ['ConvertedContactId', 'ConvertedAccountId', 'ConvertedDate', 'ConvertedOpportunityId', 'IsConverted']
            removed_count = 0
            for record in records:
                for field in readonly_fields:
                    if field in record:
                        del record[field]
                        removed_count += 1
            if removed_count > 0:
                print(f"  ℹ️  Removed {removed_count} read-only conversion field values and IsConverted flag from Lead records")
        
        # Special handling for Contract - set Status to Draft
        if object_name == "Contract":
            # Contracts must be created in Draft status, not Activated
            modified_count = 0
            for record in records:
                if "Status" in record and record["Status"] != "Draft":
                    record["Status"] = "Draft"
                    modified_count += 1
            if modified_count > 0:
                print(f"  ℹ️  Set {modified_count} Contract records to Status='Draft' (cannot create activated contracts)")
        
        # Special handling for Order - keep in Draft and remove activation fields
        if object_name == "Order":
            # Orders must be kept in Draft status to allow OrderItem insertion
            # Remove ActivatedDate and ActivatedById to prevent locking
            modified_count = 0
            for record in records:
                # Force Status to Draft
                if "Status" in record and record["Status"] != "Draft":
                    record["Status"] = "Draft"
                    modified_count += 1
                # Remove activation-related read-only fields
                if "ActivatedDate" in record:
                    del record["ActivatedDate"]
                    modified_count += 1
                if "ActivatedById" in record:
                    del record["ActivatedById"]
                    modified_count += 1
            if modified_count > 0:
                print(f"  ℹ️  Set Order records to Draft status and removed activation fields ({modified_count} changes)")
        
        # Special handling for Quote - remove read-only fields
        if object_name == "Quote":
            # AccountId is derived from Opportunity, CreatedDate is system field
            readonly_fields = ['AccountId', 'CreatedDate', 'LastModifiedDate', 'SystemModstamp']
            removed_count = 0
            for record in records:
                for field in readonly_fields:
                    if field in record:
                        del record[field]
                        removed_count += 1
            if removed_count > 0:
                print(f"  ℹ️  Removed {removed_count} read-only field values from Quote records")
        
        # Special handling for EmailMessage - RelatedToId may not be available in all orgs
        if object_name == "EmailMessage":
            # Remove RelatedToId proactively (not available in some scratch orgs / Enhanced Email required)
            removed_count = 0
            for record in records:
                if "RelatedToId" in record:
                    del record["RelatedToId"]
                    removed_count += 1
            if removed_count > 0:
                print(f"  ℹ️  Removed RelatedToId from {removed_count} EmailMessage records (field not available in scratch orgs)")
        
        # Special handling for Opportunity - remove custom fields that may not exist
        if object_name == "Opportunity":
            # Remove custom fields that may not be created during schema sync
            optional_fields = ['ContractID__c']
            removed_count = 0
            for record in records:
                for field in optional_fields:
                    if field in record:
                        del record[field]
                        removed_count += 1
            if removed_count > 0:
                print(f"  ℹ️  Removed {removed_count} optional custom field values from Opportunity records")
        
        # Special handling for OpportunityLineItem - calculate UnitPrice and remove TotalPrice
        if object_name == "OpportunityLineItem":
            # TotalPrice is a formula field (read-only), but we need to provide UnitPrice
            # Calculate: UnitPrice = TotalPrice / Quantity
            removed_count = 0
            calculated_count = 0
            for record in records:
                # Calculate UnitPrice from TotalPrice and Quantity if available
                if 'TotalPrice' in record and 'Quantity' in record:
                    try:
                        total_price = float(record['TotalPrice'])
                        quantity = float(record['Quantity'])
                        if quantity > 0:
                            unit_price = total_price / quantity
                            record['UnitPrice'] = unit_price
                            calculated_count += 1
                    except (ValueError, TypeError) as e:
                        print(f"    ⚠️  Warning: Could not calculate UnitPrice for record: {e}")
                
                # Remove TotalPrice (formula field)
                if 'TotalPrice' in record:
                    del record['TotalPrice']
                    removed_count += 1
            
            if calculated_count > 0:
                print(f"  ℹ️  Calculated UnitPrice for {calculated_count} OpportunityLineItem records")
            if removed_count > 0:
                print(f"  ℹ️  Removed {removed_count} TotalPrice values (formula field)")
        
        # Special handling for QuoteLineItem - ensure UnitPrice is set and remove TotalPrice
        if object_name == "QuoteLineItem":
            # TotalPrice is a formula field (read-only), but we need to provide UnitPrice
            # If UnitPrice exists, use it; otherwise calculate: UnitPrice = TotalPrice / Quantity
            removed_count = 0
            calculated_count = 0
            preserved_count = 0
            for record in records:
                # Check if UnitPrice is already present
                if 'UnitPrice' in record and record['UnitPrice']:
                    preserved_count += 1
                # Calculate UnitPrice from TotalPrice and Quantity if not present
                elif 'TotalPrice' in record and 'Quantity' in record:
                    try:
                        total_price = float(record['TotalPrice'])
                        quantity = float(record['Quantity'])
                        if quantity > 0:
                            unit_price = total_price / quantity
                            record['UnitPrice'] = unit_price
                            calculated_count += 1
                    except (ValueError, TypeError) as e:
                        print(f"    ⚠️  Warning: Could not calculate UnitPrice for record: {e}")
                
                # Remove TotalPrice (formula field)
                if 'TotalPrice' in record:
                    del record['TotalPrice']
                    removed_count += 1
            
            if preserved_count > 0:
                print(f"  ℹ️  Preserved existing UnitPrice for {preserved_count} QuoteLineItem records")
            if calculated_count > 0:
                print(f"  ℹ️  Calculated UnitPrice for {calculated_count} QuoteLineItem records")
            if removed_count > 0:
                print(f"  ℹ️  Removed {removed_count} TotalPrice values (formula field)")
            
            # Debug: Show first QuoteLineItem record to verify PricebookEntryId mapping
            if object_name == "QuoteLineItem" and records:
                sample = records[0]
                print(f"  🔍 Debug: First QuoteLineItem record:")
                for k in ['QuoteId', 'PricebookEntryId', 'Product2Id', 'Quantity', 'UnitPrice']:
                    if k in sample:
                        print(f"     {k}: {sample[k]}")
        
        # Special handling for OrderItem - debug logging
        if object_name == "OrderItem":
            # Debug: Show first OrderItem to verify all IDs are mapped
            if records:
                sample = records[0]
                print(f"  🔍 Debug: First OrderItem record:")
                for k in ['OrderId', 'PricebookEntryId', 'Product2Id', 'Quantity', 'UnitPrice']:
                    if k in sample:
                        print(f"     {k}: {sample[k]}")
        
        # Special handling for VoiceCallTranscript__c - remove custom fields that may not exist
        if object_name == "VoiceCallTranscript__c":
            # Remove custom lookup fields that may not be created during schema sync
            optional_fields = ['LeadId__c', 'AccountId__c', 'ContactId__c', 'OpportunityId__c', 'CaseId__c']
            removed_count = 0
            for record in records:
                for field in optional_fields:
                    if field in record:
                        del record[field]
                        removed_count += 1
            if removed_count > 0:
                print(f"  ℹ️  Removed {removed_count} optional custom field values from VoiceCallTranscript__c records")
        
        # Special handling for LiveChatTranscript - visitors are already created at the start
        # No additional preprocessing needed here
        if object_name == "LiveChatTranscript":
            pass  # LiveChatVisitors already created in upload_object()
        
        # Special handling for Order - must be Draft status
        if object_name == "Order":
            for record in records:
                if "Status" in record:
                    # Force status to Draft for new orders
                    record["Status"] = "Draft"
        
        # Special handling for Territory2 - Territory2ModelId and DeveloperName are required
        if object_name == "Territory2":
            # Territory2 records require a Territory2Model to exist
            print(f"  ℹ️  Territory2 requires a Territory2Model - checking for existing model...")
            try:
                territory_model_id = None
                
                # Try to query for Territory2Model
                try:
                    model_query = "SELECT Id, Name FROM Territory2Model LIMIT 1"
                    model_result = self.sf.query(model_query)
                    if model_result['records']:
                        territory_model_id = model_result['records'][0]['Id']
                        model_name = model_result['records'][0].get('Name', 'Unknown')
                        print(f"  ✅ Found existing Territory2Model: {model_name} ({territory_model_id})")
                    else:
                        # Territory2Model exists but empty, create one
                        print(f"  ℹ️  No Territory2Model found, creating one...")
                        new_model = self.sf.Territory2Model.create({
                            'Name': 'CRMArena Territory Model',
                            'DeveloperName': 'CRMArena_Territory_Model'
                        })
                        territory_model_id = new_model['id']
                        print(f"  ✅ Created Territory2Model: {territory_model_id}")
                except Exception as tm_err:
                    print(f"  ⚠️  Could not create Territory2Model: {tm_err}")
                    print(f"     Territory2 records will be skipped")
                    return {"uploaded": 0, "skipped": len(records), "errors": 0}
                
                # Check for Territory2Type (required field Territory2TypeId)
                print(f"  ℹ️  Territory2 requires a Territory2Type - checking...")
                territory_type_id = None
                try:
                    type_query = "SELECT Id, DeveloperName, MasterLabel FROM Territory2Type LIMIT 1"
                    type_result = self.sf.query(type_query)
                    if type_result['records']:
                        territory_type_id = type_result['records'][0]['Id']
                        type_name = type_result['records'][0].get('MasterLabel', 'Unknown')
                        print(f"  ✅ Found existing Territory2Type: {type_name} ({territory_type_id})")
                    else:
                        # Create a default Territory2Type
                        print(f"  ℹ️  No Territory2Type found, creating one...")
                        new_type = self.sf.Territory2Type.create({
                            'DeveloperName': 'Standard_Territory',
                            'MasterLabel': 'Standard Territory',
                            'Priority': 1
                        })
                        territory_type_id = new_type['id']
                        print(f"  ✅ Created Territory2Type: {territory_type_id}")
                except Exception as tt_err:
                    print(f"  ⚠️  Could not create Territory2Type: {tt_err}")
                    print(f"     Territory2 records will be skipped")
                    return {"uploaded": 0, "skipped": len(records), "errors": 0}
                
                # Update all records to use the found/created Territory2ModelId, Territory2TypeId, and generate DeveloperName
                if territory_model_id and territory_type_id:
                    dev_name_counter = {}
                    for record in records:
                        record["Territory2ModelId"] = territory_model_id
                        record["Territory2TypeId"] = territory_type_id
                        
                        # Generate DeveloperName if missing (required field, must be alphanumeric + underscore)
                        if "DeveloperName" not in record or not record["DeveloperName"]:
                            # Generate from Name field: replace spaces/special chars with underscore
                            name = record.get("Name", "Territory")
                            # Remove special characters and replace spaces with underscores
                            dev_name = ''.join(c if c.isalnum() else '_' for c in name)
                            # Remove consecutive underscores
                            dev_name = '_'.join(filter(None, dev_name.split('_')))
                            # Ensure uniqueness
                            if dev_name in dev_name_counter:
                                dev_name_counter[dev_name] += 1
                                dev_name = f"{dev_name}_{dev_name_counter[dev_name]}"
                            else:
                                dev_name_counter[dev_name] = 0
                            record["DeveloperName"] = dev_name
                    print(f"  ℹ️  Generated DeveloperName for {len(records)} Territory2 records")
                else:
                    print(f"  ⚠️  No Territory2Model available - Territory2 records will fail")
                    return {"uploaded": 0, "skipped": len(records), "errors": 0}
            except Exception as e:
                print(f"  ⚠️  Error setting up Territory2Model: {e}")
                return {"uploaded": 0, "skipped": len(records), "errors": 0}
        
        # Special handling for ProductCategory - CatalogId is required
        if object_name == "ProductCategory":
            # ProductCategory requires CatalogId which references ProductCatalog object
            # Try to find an existing ProductCatalog or create one
            print(f"  ℹ️  ProductCategory requires a ProductCatalog - checking for existing catalog...")
            try:
                catalog_id = None
                
                # Try to query for ProductCatalog
                try:
                    catalog_query = "SELECT Id, Name FROM ProductCatalog LIMIT 1"
                    catalog_result = self.sf.query(catalog_query)
                    if catalog_result['records']:
                        catalog_id = catalog_result['records'][0]['Id']
                        catalog_name = catalog_result['records'][0].get('Name', 'Unknown')
                        print(f"  ✅ Found existing ProductCatalog: {catalog_name} ({catalog_id})")
                    else:
                        # ProductCatalog exists but empty, create one
                        print(f"  ℹ️  No ProductCatalog found, creating one...")
                        new_catalog = self.sf.ProductCatalog.create({
                            'Name': 'CRMArena Default Catalog'
                        })
                        catalog_id = new_catalog['id']
                        print(f"  ✅ Created ProductCatalog: {catalog_id}")
                except Exception as pc_err:
                    # ProductCatalog doesn't exist, fall back to old behavior
                    print(f"  ⚠️  ProductCatalog object not available: {pc_err}")
                    # Try legacy Catalog object names
                    for catalog_obj_name in ["Catalog__c", "Catalog"]:
                        try:
                            catalog_query = f"SELECT Id FROM {catalog_obj_name} LIMIT 1"
                            catalog_result = self.sf.query(catalog_query)
                            if catalog_result['records']:
                                catalog_id = catalog_result['records'][0]['Id']
                                print(f"  ℹ️  Found existing {catalog_obj_name}: {catalog_id}")
                                break
                        except:
                            continue
                
                # Update all records to use the found/created CatalogId
                if catalog_id:
                    for record in records:
                        record["CatalogId"] = catalog_id
                else:
                    print(f"  ⚠️  No ProductCatalog found - ProductCategory records will fail")
                    print(f"     See ENABLE_PRODUCT_CATEGORY.md for setup instructions")
            except Exception as e:
                print(f"  ⚠️  Could not query for ProductCatalog: {e}")
                print(f"     ProductCategory records may fail - see ENABLE_PRODUCT_CATEGORY.md")
        
        # Upload to Salesforce using Bulk API
        try:
            # Determine whether to use upsert or insert
            # Upsert requires External ID field with proper FLS permissions
            use_upsert = True
            external_id_field = "OriginalId__c"
            
            # Knowledge__kav doesn't support External ID on custom fields, use insert
            if object_name == "Knowledge__kav":
                use_upsert = False
                print(f"  📥 Using insert for Knowledge articles (no External ID support)...")
            # User object: Always use insert (can't upsert Users, Username is the unique key)
            elif object_name == "User":
                use_upsert = False
                print(f"  📥 Using insert for User (User object doesn't support upsert via External ID)...")
            else:
                # Check if OriginalId__c field exists and is accessible for ALL objects
                try:
                    # Try to describe the object
                    describe = self.sf.__getattr__(object_name).describe()
                    field_names = [f['name'] for f in describe['fields']]
                    
                    if 'OriginalId__c' not in field_names:
                        use_upsert = False
                        print(f"  📥 Using insert (OriginalId__c not found on {object_name})...")
                        
                        # Debug: Show if field actually exists but isn't readable
                        try:
                            # Try to query with OriginalId__c to see if it exists but isn't in describe
                            test_query = f"SELECT Id, OriginalId__c FROM {object_name} LIMIT 1"
                            self.sf.query(test_query)
                            # If this works, field exists but wasn't in describe (metadata cache issue)
                            print(f"     ℹ️  Note: OriginalId__c actually exists on {object_name} but not showing in describe()")
                            print(f"     This may be due to metadata caching - upsert might still work")
                        except Exception:
                            # Field truly doesn't exist
                            pass
                except Exception as e:
                    use_upsert = False
                    print(f"  📥 Using insert (could not verify OriginalId__c on {object_name}: {str(e)[:100]})")
            
            # Batch size / concurrency settings
            # Use serial mode for PricebookEntry to avoid UNABLE_TO_LOCK_ROW issues.
            # Use serial mode for ALL objects to avoid concurrency/lock issues
            # Use REST API (one-by-one) for OrderItem as Bulk API has issues with Draft Orders
            if object_name == "OrderItem":
                # OrderItem needs individual inserts (not bulk) to work with Draft Orders
                batch_size = 1
                use_serial_flag = True
                use_bulk = False  # Force REST API
                print(f"  ℹ️  Using REST API (individual inserts) for OrderItem")
            elif object_name in ["PricebookEntry", "Task", "Event"]:
                # These objects are particularly prone to timeouts and lock issues
                batch_size = 1000
                use_serial_flag = True
            else:
                # Use serial mode with batch size 1000 for all other objects as well
                batch_size = 1000
                use_serial_flag = True
            
            if use_upsert:
                print(f"  🔄 Using upsert with {external_id_field} (batches of {batch_size}, "
                      f"{'serial' if use_serial_flag else 'parallel'})...")
                try:
                    if 'use_bulk' in locals() and not use_bulk:
                        # REST API one-by-one (for OrderItem)
                        results = []
                        for i, record in enumerate(records):
                            try:
                                # Use upsert with external ID
                                result = self.sf.__getattr__(object_name).upsert(
                                    f"{external_id_field}/{record.get(external_id_field)}", 
                                    record
                                )
                                results.append({'success': True, 'id': result.get('id')})
                                if (i + 1) % 50 == 0:
                                    print(f"    Progress: {i + 1}/{len(records)} uploaded...")
                            except Exception as e:
                                results.append({'success': False, 'errors': [{'message': str(e)}]})
                    else:
                        results = self.sf.bulk.__getattr__(object_name).upsert(
                            records,
                            external_id_field,
                            batch_size=batch_size,
                            use_serial=use_serial_flag
                        )
                except Exception as upsert_error:
                    if "not readable" in str(upsert_error).lower() or "not found" in str(upsert_error).lower():
                        print(f"  ⚠️  Upsert failed (field not accessible), falling back to insert...")
                        use_upsert = False
                    else:
                        raise upsert_error
            
            if not use_upsert:
                # Remove OriginalId__c field from records for insert mode (field may not exist)
                for record in records:
                    record.pop('OriginalId__c', None)
                print(f"  📥 Using insert (batches of {batch_size}, "
                      f"{'serial' if use_serial_flag else 'parallel'})...")
                
                if 'use_bulk' in locals() and not use_bulk:
                    # REST API one-by-one (for OrderItem)
                    results = []
                    for i, record in enumerate(records):
                        try:
                            result = self.sf.__getattr__(object_name).create(record)
                            results.append({'success': True, 'id': result.get('id')})
                            if (i + 1) % 50 == 0:
                                print(f"    Progress: {i + 1}/{len(records)} uploaded...")
                        except Exception as e:
                            results.append({'success': False, 'errors': [{'message': str(e), 'statusCode': 'API_ERROR'}]})
                else:
                    results = self.sf.bulk.__getattr__(object_name).insert(
                        records,
                        batch_size=batch_size,
                        use_serial=use_serial_flag
                    )
            
            # Process results
            uploaded = 0
            errors = 0
            quote_errors_shown = 0  # Track Quote errors separately for debugging
            
            for idx, result in enumerate(results):
                if result['success']:
                    uploaded += 1
                else:
                    # Some errors we treat as non-fatal warnings (do not count toward "errors")
                    handled_as_warning = False
                    error_details = result.get('errors', [{}])
                    if error_details:
                        err0 = error_details[0]
                        error_msg = err0.get('message', 'Unknown error')
                        error_fields = err0.get('fields', [])
                        status_code = err0.get('statusCode')
                        # Handle specific errors gracefully
                        if status_code == 'DUPLICATE_USERNAME' and object_name == "User":
                            print(f"    ⚠️  Skipping User - duplicate Username (already exists)")
                            handled_as_warning = True
                        elif status_code == 'LICENSE_LIMIT_EXCEEDED' and object_name == "User":
                            print(f"    ⚠️  Skipping User - license limit exceeded (Developer orgs typically allow 2-3 users)")
                            handled_as_warning = True
                        elif status_code == 'INSUFFICIENT_ACCESS' and 'Manage Users' in error_msg:
                            print(f"    ❌ Error: Manage Users permission required")
                            print(f"       See ENABLE_USER_CREATION.md for setup instructions")
                        elif status_code == 'INVALID_CROSS_REFERENCE_KEY' and object_name == "ProductCategory":
                            print(f"    ⚠️  Skipping ProductCategory - CatalogId does not exist")
                            print(f"       See ENABLE_PRODUCT_CATEGORY.md for setup instructions")
                            handled_as_warning = True
                        elif status_code == 'STANDARD_PRICE_NOT_DEFINED' and object_name == "PricebookEntry":
                            # Standard price not defined for this product in the standard pricebook.
                            # We've already attempted to create standard entries in bulk; treat remaining
                            # cases as safe-to-skip extras (they won't break referential integrity).
                            print(f"    ⚠️  Skipping PricebookEntry - standard price not defined (extra entry)")
                            handled_as_warning = True
                        elif status_code == 'DUPLICATE_VALUE' and object_name == "PricebookEntry":
                            # Duplicate PricebookEntry (same product/pricebook) - record already exists.
                            print(f"    ⚠️  Skipping duplicate PricebookEntry - record already exists")
                            handled_as_warning = True
                        elif status_code == 'INVALID_FIELD' and 'CaseId__c' in error_msg and object_name == "CaseHistory__c":
                            print(f"    ⚠️  Skipping CaseHistory__c record - CaseId__c field does not exist")
                            handled_as_warning = True
                        elif status_code == 'INVALID_FIELD' and 'RelatedToId' in error_msg and object_name == "EmailMessage":
                            # RelatedToId field not available in this org (may require Enhanced Email or specific features)
                            print(f"    ⚠️  Skipping EmailMessage record - RelatedToId field not available in this org")
                            handled_as_warning = True
                        elif status_code == 'INSUFFICIENT_ACCESS_ON_CROSS_REFERENCE_ENTITY' and object_name == "LiveChatTranscript":
                            # LiveChatTranscript referencing a Lead/Contact/Case that isn't accessible
                            # Extract the ID from error message if possible
                            ref_id = error_msg.split('id:')[-1].strip() if 'id:' in error_msg else 'unknown'
                            print(f"    ⚠️  Skipping LiveChatTranscript - insufficient access to referenced record ({ref_id[:15]}...)")
                            handled_as_warning = True
                        elif status_code == 'INVALID_FIELD':
                            # Various objects with custom fields or invalid fields
                            if object_name == "VoiceCallTranscript__c" and any(field in error_msg for field in ['LeadId__c', 'AccountId__c', 'ContactId__c', 'OpportunityId__c', 'CaseId__c']):
                                if errors < 3:
                                    print(f"    ⚠️  Skipping VoiceCallTranscript__c - custom lookup field not available: {error_msg[:100]}")
                                handled_as_warning = True
                            elif object_name == "VoiceCallTranscript__c" and 'TranscriptBody__c' in error_msg:
                                # TranscriptBody__c field should have been created by schema sync - print all errors
                                if errors < 10:
                                    print(f"    ❌ VoiceCallTranscript__c error - TranscriptBody__c field issue: {error_msg[:150]}")
                                handled_as_warning = True
                            elif object_name == "Issue__c" and 'IssueDescription__c' in error_msg:
                                # IssueDescription__c field should have been created by schema sync - print all errors
                                if errors < 10:
                                    print(f"    ❌ Issue__c error - IssueDescription__c field issue: {error_msg[:150]}")
                                handled_as_warning = True
                            elif object_name == "Opportunity" and 'ContractID__c' in error_msg:
                                print(f"    ⚠️  Skipping Opportunity - ContractID__c custom field not available")
                                handled_as_warning = True
                            else:
                                # Other INVALID_FIELD errors - print first few to help debug
                                if errors < 3:
                                    print(f"    ⚠️  Skipping {object_name} record - invalid field: {error_msg[:100]}")
                                handled_as_warning = True
                        elif status_code == 'INVALID_FIELD_FOR_INSERT_UPDATE':
                            # Read-only fields
                            if object_name in ["OpportunityLineItem", "QuoteLineItem"] and 'TotalPrice' in error_msg:
                                print(f"    ⚠️  Skipping {object_name} - TotalPrice is a read-only formula field")
                                handled_as_warning = True
                            elif object_name == "Lead" and any(field in error_msg for field in ['ConvertedContactId', 'ConvertedAccountId', 'ConvertedDate', 'ConvertedOpportunityId']):
                                print(f"    ⚠️  Skipping Lead - conversion fields are read-only")
                                handled_as_warning = True
                        elif status_code == 'FIELD_INTEGRITY_EXCEPTION' and object_name == "Lead":
                            # Lead conversion integrity error (IsConverted=True but ConvertedAccountId is empty)
                            if 'Converted Account' in error_msg or 'ConvertedAccountId' in error_msg:
                                print(f"    ⚠️  Skipping Lead - conversion field integrity issue (IsConverted without ConvertedAccountId)")
                                handled_as_warning = True
                        elif status_code == 'DUPLICATES_DETECTED' and object_name == "Lead":
                            # Duplicate Lead (based on email or other duplicate rules)
                            print(f"    ⚠️  Skipping Lead - duplicate detected")
                            handled_as_warning = True
                        elif status_code == 'REQUIRED_FIELD_MISSING' and object_name == "Territory2":
                            # Territory2 missing required field (likely DeveloperName)
                            if 'DeveloperName' in error_msg:
                                print(f"    ⚠️  Skipping Territory2 - DeveloperName is required")
                                handled_as_warning = True
                        elif status_code == 'REQUIRED_FIELD_MISSING' and object_name == "Quote":
                            # Quote missing required field - make visible for debugging
                            if quote_errors_shown < 5:
                                print(f"    ❌ Quote error - required field missing: {error_msg[:150]}")
                                if error_fields:
                                    print(f"       Fields: {error_fields}")
                                quote_errors_shown += 1
                            handled_as_warning = True
                        elif status_code == 'INVALID_CROSS_REFERENCE_KEY':
                            # Invalid cross-reference (referencing record that doesn't exist or isn't accessible)
                            if object_name == "UserTerritory2Association":
                                # Show UserTerritory2Association errors for debugging
                                if idx < 5:
                                    print(f"    🔍 UserTerritory2Association Debug Error #{idx+1}:")
                                    print(f"       Message: {error_msg[:200]}")
                                    print(f"       StatusCode: {status_code}")
                                    print(f"       Fields: {error_fields}")
                                handled_as_warning = True
                            elif object_name == "Territory2":
                                # Show Territory2 errors for debugging (any cross-reference error)
                                if errors < 5:
                                    print(f"    ❌ Territory2 error: {error_msg[:200]}")
                                    if error_fields:
                                        print(f"       Fields: {error_fields}")
                                    if status_code:
                                        print(f"       StatusCode: {status_code}")
                                handled_as_warning = True
                            elif object_name == "Quote":
                                # Quote errors should be visible for debugging - print first 5
                                if quote_errors_shown < 5:
                                    print(f"    ❌ Quote error - invalid cross-reference: {error_msg[:150]}")
                                    if error_fields:
                                        print(f"       Fields: {error_fields}")
                                    quote_errors_shown += 1
                                handled_as_warning = True
                            else:
                                # Generic cross-reference error for other objects - print first few to help debug
                                if errors < 3:
                                    print(f"    ⚠️  Skipping {object_name} record - invalid cross-reference: {error_msg[:100]}")
                                handled_as_warning = True
                        elif object_name == "Contact" and status_code in ('DUPLICATE_VALUE', 'DUPLICATES_DETECTED'):
                            # Duplicate Contact (e.g., Email-based duplicate rule).
                            # Map the source Contact Id to the existing Salesforce Contact by Email.
                            try:
                                email = None
                                if idx < len(records):
                                    rec = records[idx]
                                    email = rec.get("Email")
                                if email:
                                    # Query existing Contact by email
                                    email_escaped = str(email).replace("'", "\\'")
                                    contact_query = (
                                        f"SELECT Id FROM Contact "
                                        f"WHERE Email = '{email_escaped}' "
                                        f"LIMIT 1"
                                    )
                                    existing = self.sf.query(contact_query)
                                    existing_records = existing.get("records", [])
                                    if existing_records:
                                        existing_id = existing_records[0].get("Id")
                                        # Map old source Id -> existing Salesforce Id
                                        if idx < len(old_ids):
                                            old_id = old_ids[idx]
                                            if old_id and existing_id:
                                                self.id_mapping_db.save_mapping(
                                                    "Contact",
                                                    str(old_id),
                                                    existing_id,
                                                )
                                                print(
                                                    f"    ℹ️  Mapped duplicate Contact "
                                                    f"{str(old_id)[:15]}... -> {existing_id[:15]}... "
                                                    f"based on Email {email}"
                                                )
                                                handled_as_warning = True
                            except Exception as map_err:
                                print(
                                    f"    ⚠️  Could not map duplicate Contact by Email: "
                                    f"{str(map_err)[:200]}"
                                )
                        else:
                            # Print errors for Quote to help debug, treat as warnings for other objects based on context
                            if object_name == "Quote" and quote_errors_shown < 5:
                                print(f"    ❌ Quote error: {error_msg[:150]}")
                                if status_code:
                                    print(f"       StatusCode: {status_code}")
                                if error_fields:
                                    print(f"       Fields: {error_fields}")
                                quote_errors_shown += 1
                                handled_as_warning = True
                            else:
                                print(f"    ❌ Error: {error_msg}")
                                if status_code:
                                    print(f"       StatusCode: {status_code}")
                                if error_fields:
                                    print(f"       Fields: {error_fields}")
                    else:
                        print(f"    ❌ Error: {result}")

                    if not handled_as_warning:
                        errors += 1
                    
                    # Special: Always show Territory2 errors for debugging
                    if object_name == "Territory2" and not result['success']:
                        if idx < 5:  # Show first 5 errors
                            err_details = result.get('errors', [{}])
                            if err_details:
                                err = err_details[0]
                                print(f"    🔍 Territory2 Debug Error #{idx+1}:")
                                print(f"       Message: {err.get('message', 'Unknown')}")
                                print(f"       StatusCode: {err.get('statusCode', 'Unknown')}")
                                print(f"       Fields: {err.get('fields', [])}")
            
            # Store ID mappings to persistent database
            # Match old_ids with new_ids based on successful uploads
            # results and records are in the same order, so index i matches
            mappings_to_save = []
            mappings_shown = 0
            for i, result in enumerate(results):
                if result['success'] and i < len(old_ids):
                    old_id = old_ids[i]
                    new_id = result.get('id')
                    if old_id and new_id:
                        mappings_to_save.append((str(old_id), new_id))
                        # Debug: show first few mappings
                        if mappings_shown < 3:
                            print(f"    ℹ️  Mapped {object_name}: {str(old_id)[:15]}... -> {new_id[:15]}...")
                            mappings_shown += 1
            
            
            # Save all mappings to database in batch
            if mappings_to_save:
                self.id_mapping_db.save_mappings_batch(object_name, mappings_to_save)
                print(f"    💾 Saved {len(mappings_to_save)} ID mappings to database")
            
            print(f"  ✅ Upserted: {uploaded}, Errors: {errors}")
            return {"uploaded": uploaded, "skipped": 0, "errors": errors}
            
        except Exception as e:
            print(f"  ❌ Upload failed: {e}")
            import traceback
            traceback.print_exc()
            return {"uploaded": 0, "skipped": 0, "errors": len(records)}
    
    def _get_referenced_object(self, field_name: str, object_name: str) -> Optional[str]:
        """Determine which object a lookup field references."""
        # Common patterns
        if field_name == "AccountId":
            return "Account"
        elif field_name == "ContactId":
            return "Contact"
        elif field_name == "OwnerId":
            return "User"
        elif field_name == "CaseId" or field_name == "CaseId__c":
            return "Case"
        elif field_name == "LeadId":
            return "Lead"
        elif field_name == "OpportunityId":
            return "Opportunity"
        elif field_name == "QuoteId":
            return "Quote"
        elif field_name == "ContractId":
            return "Contract"
        elif field_name == "Product2Id":
            return "Product2"
        elif field_name == "Pricebook2Id":
            return "Pricebook2"
        elif field_name == "OrderId":
            return "Order"
        elif field_name == "Territory2Id":
            return "Territory2"
        elif field_name == "ProductCategoryId":
            return "ProductCategory"
        elif field_name == "IssueId__c":
            return "Issue__c"
        elif field_name == "OrderItemId__c":
            return "OrderItem"
        elif field_name == "PricebookEntryId":
            return "PricebookEntry"
        elif field_name == "OpportunityLineItemId":
            return "OpportunityLineItem"
        elif field_name == "LiveChatVisitorId":
            return "LiveChatVisitor"
        elif field_name == "ParentId":
            # Could be Case or other objects - check context
            if object_name == "EmailMessage":
                return "Case"
        elif field_name == "ProductId":
            return "Product2"
        elif field_name == "WhatId":
            # Generic reference field - context dependent
            # Common in Task/Event - could be Opportunity, Account, Case, etc.
            # Infer from ID prefix in the value (will be checked in the mapping logic)
            # Return a placeholder - the actual mapping will use ID prefix detection
            return "Polymorphic"  # Special marker for polymorphic fields
        elif field_name == "WhoId":
            # Polymorphic field - can reference Lead or Contact
            return "Polymorphic"  # Special marker for polymorphic fields
        
        return None
    
    def convert_leads_post_upload(self):
        """
        Convert Leads after all data is uploaded.
        This preserves the original Lead conversion relationships.
        """
        print("\n" + "="*60)
        print("Post-Upload: Converting Leads")
        print("="*60 + "\n")
        
        try:
            # Query source database for converted Leads
            cursor = self.db.cursor()
            
            # Check which conversion columns exist
            cursor.execute("PRAGMA table_info(Lead)")
            lead_columns = {row[1] for row in cursor.fetchall()}
            
            has_converted_opp = 'ConvertedOpportunityId' in lead_columns
            has_converted_date = 'ConvertedDate' in lead_columns
            
            # Build SELECT clause based on available columns
            select_clause = "Id, ConvertedAccountId, ConvertedContactId"
            if has_converted_opp:
                select_clause += ", ConvertedOpportunityId"
            else:
                select_clause += ", NULL as ConvertedOpportunityId"
            if has_converted_date:
                select_clause += ", ConvertedDate"
            else:
                select_clause += ", NULL as ConvertedDate"
            
            cursor.execute(f"""
                SELECT {select_clause}
                FROM Lead
                WHERE IsConverted = 1
                  AND ConvertedAccountId IS NOT NULL
                  AND ConvertedContactId IS NOT NULL
            """)
            converted_leads = cursor.fetchall()
            
            if not converted_leads:
                print("  ℹ️  No converted Leads found in source data")
                return {"converted": 0, "errors": 0}
            
            print(f"  Found {len(converted_leads)} converted Leads in source data")
            
            converted_count = 0
            error_count = 0
            
            for old_lead_id, old_account_id, old_contact_id, old_opp_id, converted_date in converted_leads:
                try:
                    # Get new IDs from mapping
                    new_lead_id = self.id_mapping_db.get_mapping('Lead', old_lead_id)
                    new_account_id = self.id_mapping_db.get_mapping('Account', old_account_id)
                    new_contact_id = self.id_mapping_db.get_mapping('Contact', old_contact_id)
                    
                    if not new_lead_id:
                        if error_count < 3:
                            print(f"    ⚠️  Skipping Lead {old_lead_id} - not found in mappings")
                        error_count += 1
                        continue
                    if not new_account_id:
                        if error_count < 3:
                            print(f"    ⚠️  Skipping Lead {old_lead_id} - ConvertedAccountId not found in mappings")
                        error_count += 1
                        continue
                    if not new_contact_id:
                        if error_count < 3:
                            print(f"    ⚠️  Skipping Lead {old_lead_id} - ConvertedContactId not found in mappings")
                        error_count += 1
                        continue
                    
                    # Check if Opportunity exists
                    new_opp_id = None
                    do_not_create_opp = True
                    if old_opp_id:
                        new_opp_id = self.id_mapping_db.get_mapping('Opportunity', old_opp_id)
                        if new_opp_id:
                            do_not_create_opp = False  # Use existing Opportunity
                    
                    # Convert the Lead using Salesforce API
                    convert_data = {
                        'convertedStatus': 'Closed - Converted',
                        'accountId': new_account_id,
                        'contactId': new_contact_id,
                        'doNotCreateOpportunity': do_not_create_opp,
                        'sendNotificationEmail': False,
                        'overwriteLeadSource': False
                    }
                    
                    if new_opp_id:
                        convert_data['opportunityId'] = new_opp_id
                    
                    # Make the API call
                    response = self.sf.restful(
                        f'sobjects/Lead/{new_lead_id}/convert',
                        method='POST',
                        data=convert_data
                    )
                    
                    if response.get('success'):
                        converted_count += 1
                        if converted_count % 50 == 0:
                            print(f"    ✅ Converted {converted_count}/{len(converted_leads)} Leads...")
                    else:
                        error_count += 1
                        errors = response.get('errors', [])
                        if error_count <= 3:
                            print(f"    ❌ Failed to convert Lead {old_lead_id}: {errors}")
                
                except Exception as e:
                    error_count += 1
                    error_str = str(e)
                    # Only show first few errors
                    if error_count <= 3:
                        print(f"    ❌ Error converting Lead {old_lead_id}: {error_str[:100]}")
                    elif error_count == 4:
                        print(f"    ⚠️  Suppressing further conversion errors...")
            
            print(f"\n  ✅ Successfully converted {converted_count} Leads")
            if error_count > 0:
                print(f"  ⚠️  Failed to convert {error_count} Leads")
            
            return {"converted": converted_count, "errors": error_count}
        
        except Exception as e:
            print(f"  ❌ Error during Lead conversion: {e}")
            return {"converted": 0, "errors": 0}
    
    def upload_all(self, limit_per_object: Optional[int] = None, skip_objects: List[str] = None, 
                   only_object: Optional[List[str]] = None):
        """Upload all objects in the correct order."""
        skip_objects = skip_objects or []
        
        # If only_object is specified, only upload those ones
        if only_object:
            objects_to_upload = only_object
        else:
            objects_to_upload = UPLOAD_ORDER
        
        print(f"\n{'='*60}")
        print("Uploading CRMArena Data to Salesforce")
        print(f"{'='*60}\n")
        
        stats = {
            "total_uploaded": 0,
            "total_errors": 0,
            "objects": {}
        }
        
        for object_name in objects_to_upload:
            if object_name in skip_objects:
                print(f"\n⏭️  Skipping {object_name}")
                continue
            
            # Special: Ensure PricebookEntries before OrderItem upload
            if object_name == "OrderItem" and not self.dry_run:
                self._ensure_pricebook_entries_for_orders()
                # Note: DO NOT activate Orders before adding OrderItems!
                # OrderItems can only be added to Draft Orders that have never been activated.
            
            try:
                result = self.upload_object(object_name, limit=limit_per_object)
                stats["objects"][object_name] = result
                stats["total_uploaded"] += result["uploaded"]
                stats["total_errors"] += result["errors"]
                
                # Small delay between objects
                if not self.dry_run:
                    time.sleep(1)
                    
            except Exception as e:
                print(f"  ❌ Failed to upload {object_name}: {e}")
                stats["objects"][object_name] = {"uploaded": 0, "skipped": 0, "errors": 1}
                stats["total_errors"] += 1
        
        # Post-upload: Convert Leads to preserve conversion relationships
        if "Lead" in objects_to_upload and "Lead" not in skip_objects and not self.dry_run:
            conversion_result = self.convert_leads_post_upload()
            stats["leads_converted"] = conversion_result.get("converted", 0)
            stats["conversion_errors"] = conversion_result.get("errors", 0)
        
        # Print summary
        print(f"\n{'='*60}")
        print("Upload Summary")
        print(f"{'='*60}")
        print(f"Total records uploaded: {stats['total_uploaded']}")
        print(f"Total errors: {stats['total_errors']}")
        if "leads_converted" in stats:
            print(f"Leads converted: {stats['leads_converted']}")
            if stats.get("conversion_errors", 0) > 0:
                print(f"Lead conversion errors: {stats['conversion_errors']}")
        print(f"\nPer-object breakdown:")
        for obj_name, result in stats["objects"].items():
            if result["uploaded"] > 0 or result["errors"] > 0:
                print(f"  {obj_name}: {result['uploaded']} uploaded, {result['errors']} errors")
        print(f"{'='*60}\n")
        
        if self.dry_run:
            print("🔍 This was a DRY RUN - no data was actually uploaded")
            print("   Run without --dry-run to upload data\n")

def main():
    parser = argparse.ArgumentParser(
        description="Upload CRMArena data from SQLite to Salesforce"
    )
    parser.add_argument(
        "--org_type",
        type=str,
        default="original",
        choices=["original", "b2b", "b2c"],
        help="Organization type"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview upload without actually uploading"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of records per object (for testing)"
    )
    parser.add_argument(
        "--skip",
        type=str,
        nargs="+",
        default=[],
        help="Objects to skip (e.g., --skip Knowledge__kav User)"
    )
    parser.add_argument(
        "--only",
        type=str,
        nargs="+",
        default=None,
        help="Upload only these objects (e.g., --only Quote QuoteLineItem)"
    )
    parser.add_argument(
        "--clear-mappings",
        action="store_true",
        help="Clear all ID mappings from the database before uploading"
    )
    parser.add_argument(
        "--show-mappings",
        action="store_true",
        help="Show current ID mapping statistics and exit"
    )
    
    args = parser.parse_args()
    
    # Handle show-mappings flag
    if args.show_mappings:
        db = IdMappingDB()
        total = db.get_count()
        print(f"\n{'='*60}")
        print("ID Mapping Statistics")
        print(f"{'='*60}")
        print(f"Database: {db.db_path}")
        print(f"Total mappings: {total}")
        print()
        for obj in UPLOAD_ORDER:
            count = db.get_count(obj)
            if count > 0:
                print(f"  {obj}: {count} mappings")
        print(f"{'='*60}\n")
        db.close()
        return 0
    
    # Handle clear-mappings flag
    if args.clear_mappings:
        db = IdMappingDB()
        count = db.get_count()
        if count > 0:
            print(f"🗑️  Clearing {count} ID mappings from database...")
            db.clear_all()
            print("✅ All ID mappings cleared")
        else:
            print("ℹ️  No ID mappings to clear")
        db.close()
        if not args.dry_run and args.limit is None and not args.only:
            # Only cleared mappings, nothing to upload
            return 0
    
    try:
        uploader = DataUploader(org_type=args.org_type, dry_run=args.dry_run)
        uploader.upload_all(limit_per_object=args.limit, skip_objects=args.skip, only_object=args.only)
        return 0
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())

