#!/usr/bin/env python3
"""
Automated script to sync CRMArena schema to your Salesforce Developer org.

This script:
1. Reads the exported schema JSON
2. Automatically creates custom objects and fields in your Salesforce org
3. Uses Salesforce Tooling API for programmatic schema creation

Usage:
    python sync_schema_to_salesforce.py --org_type original [--dry-run] [--skip-existing]
"""

import json
import os
import argparse
import time
import requests
import zipfile
import tempfile
import base64
import xml.etree.ElementTree as ET
import subprocess
from typing import Dict, List, Optional, Set
from dotenv import load_dotenv
from simple_salesforce import Salesforce
from zeep import Client
from zeep.transports import Transport

# Standard Salesforce objects that already exist
STANDARD_OBJECTS = {
    "User", "Account", "Contact", "Case", "Lead", "Opportunity",
    "Product2", "Pricebook2", "PricebookEntry", "Order", "OrderItem",
    "EmailMessage", "LiveChatTranscript", "ProductCategory", 
    "ProductCategoryProduct", "Knowledge__kav"
}

# Field type mappings based on field name patterns and descriptions
def infer_field_type(field_name: str, description: str, object_name: str) -> Dict:
    """Infer Salesforce field type from field name and description."""
    field_lower = field_name.lower()
    desc_lower = description.lower()
    
    # Lookup/Reference fields - check FIRST before other types
    if field_name.endswith("Id") or field_name.endswith("Id__c"):
        # Check multiple patterns for references
        if (
            "references" in desc_lower
            or "associated with" in desc_lower
            or "related to" in desc_lower
            or "id of the" in desc_lower
        ):
            referenced_obj = extract_referenced_object(description, field_name)
            if referenced_obj:
                # Generate relationship name (can't contain __c, must be alphanumeric, start with letter)
                rel_name = field_name.replace("Id__c", "").replace("Id", "").replace("__c", "")
                # Remove any remaining underscores and capitalize
                rel_name = "".join(word.capitalize() for word in rel_name.split("_") if word)
                # If nothing is left (edge case), fall back to a generic name
                if not rel_name:
                    rel_name = "Ref"
                # Ensure it starts with a letter and is valid
                if not rel_name[0].isalpha():
                    rel_name = "Ref" + rel_name
                relationship_name = f"{object_name.replace('__c', '')}{rel_name}"
                return {
                    "type": "Lookup",
                    "referenceTo": referenced_obj,
                    "relationshipName": relationship_name,
                }
    
    # Picklist fields (check before Date to catch date-related picklists)
    if "one of" in desc_lower:
        values = extract_picklist_values(description)
        if values:
            return {
                "type": "Picklist",
                "valueSet": {"valueSetDefinition": {"sorted": False, "value": values}}
            }
    
    # Date/DateTime fields
    if "date" in desc_lower or "timestamp" in desc_lower:
        # Check for DateTime format indicators
        if ("format" in desc_lower and "T" in description) or "YYYY-MM-DDTHH:MM:SS" in description:
            return {"type": "DateTime"}
        # If field name suggests date/time
        if field_name in ["CreatedDate", "LastModifiedDate", "ClosedDate", "EndTime", "MessageDate"]:
            return {"type": "DateTime"}
        return {"type": "Date"}
    
    # Boolean fields - but NOT fields that just happen to start with "Is" in the middle
    # Only match if "Is" is followed by a capital letter (IsActive, IsDeleted, etc.)
    if (field_name.startswith("Is") and len(field_name) > 2 and field_name[2].isupper()) or "boolean" in desc_lower:
        return {"type": "Checkbox", "defaultValue": False}
    
    # Email fields
    if "email" in field_lower:
        return {"type": "Email"}
    
    # Phone fields
    if "phone" in field_lower:
        return {"type": "Phone"}
    
    # URL fields
    if "url" in field_lower or field_name == "UrlName":
        return {"type": "Url"}
    
    # Number fields
    if "number" in desc_lower or "quantity" in desc_lower or "price" in desc_lower:
        return {"type": "Number", "precision": 18, "scale": 2}
    
    # Text fields (default)
    if len(description) > 255 or "description" in desc_lower or "content" in desc_lower:
        return {"type": "LongTextArea", "length": 32000, "visibleLines": 3}
    
    # Default to Text
    return {"type": "Text", "length": 255}

def extract_referenced_object(description: str, field_name: str = None) -> str:
    """Extract referenced object name from description."""
    import re
    
    # Pattern 1: "References X object" or "References X"
    match = re.search(r'References\s+(\w+)(?:\s+object)?', description, re.IGNORECASE)
    if match:
        obj_name = match.group(1)
        # Handle custom objects
        if obj_name.endswith("__c"):
            return obj_name
        # Return standard object name
        return obj_name
    
    # Pattern 2: "ID of the X" - extract X and convert to object name
    # Handle patterns like "ID of the Issue", "ID of the Order Item"
    # More flexible pattern that doesn't require capital letter
    match = re.search(r'ID of the\s+([\w\s]+?)(?:\s+associated|\s+related|\.|$)', description, re.IGNORECASE)
    if match:
        obj_name_raw = match.group(1).strip()
        # Convert to proper object name - remove spaces and capitalize properly
        # "Issue" -> "Issue", "Order Item" -> "OrderItem"
        obj_name = "".join(word.capitalize() for word in obj_name_raw.split())
        
        # Check if it's a standard object (case-insensitive)
        standard_objects_lower = {obj.lower() for obj in STANDARD_OBJECTS}
        obj_name_lower = obj_name.lower()
        
        # If it's a standard object, return as-is (no __c)
        if obj_name_lower in standard_objects_lower:
            # Find the matching standard object name (preserve case)
            for std_obj in STANDARD_OBJECTS:
                if std_obj.lower() == obj_name_lower:
                    return std_obj
        
        # If it's a custom field (ends with __c), the object is likely custom too
        if field_name and field_name.endswith("__c"):
            if not obj_name.endswith("__c"):
                obj_name = obj_name + "__c"
        return obj_name
    
    # Pattern 3: "associated with this X" or "related to this X"
    match = re.search(r'(?:associated with|related to)\s+(?:this\s+)?(\w+)', description, re.IGNORECASE)
    if match:
        obj_name = match.group(1)
        obj_name = obj_name.replace(" ", "")
        if field_name and field_name.endswith("__c") and not obj_name.endswith("__c"):
            obj_name = obj_name + "__c"
        return obj_name
    
    # Pattern 4: If field name suggests an object (e.g., IssueId__c -> Issue__c)
    if field_name:
        # Remove Id and __c to get object name
        obj_candidate = field_name.replace("Id__c", "").replace("Id", "").replace("__c", "")
        if obj_candidate:
            # Capitalize first letter
            obj_candidate = obj_candidate[0].upper() + obj_candidate[1:] if obj_candidate else ""
            # If field ends with __c, object is likely custom
            if field_name.endswith("__c"):
                if not obj_candidate.endswith("__c"):
                    obj_candidate = obj_candidate + "__c"
            return obj_candidate
    
    return None

def extract_picklist_values(description: str) -> List[Dict]:
    """Extract picklist values from description."""
    import re
    # Look for patterns like "One of ['value1', 'value2', 'value3']"
    # Handle both single and double quotes
    match = re.search(r"One of\s+\[(.*?)\]", description, re.IGNORECASE)
    if match:
        values_str = match.group(1)
        # Split by comma, handling quotes
        values = []
        # Try to parse values with quotes
        value_matches = re.findall(r"['\"](.*?)['\"]", values_str)
        if value_matches:
            values = value_matches
        else:
            # Fallback: split by comma
            values = [v.strip().strip("'\"") for v in values_str.split(",")]
        
        # Filter out empty values and create picklist entries
        picklist_values = [{"fullName": v, "default": False} for v in values if v.strip()]
        if picklist_values:
            return picklist_values
    
    # Look for patterns like "e.g., 'value1', 'value2'"
    match = re.search(r"e\.g\.\s*['\"](.*?)['\"]", description, re.IGNORECASE)
    if match:
        # This is just an example, not all values
        return None
    
    return None

class SchemaSyncer:
    def __init__(self, org_type: str = "original", dry_run: bool = False):
        """Initialize the schema syncer."""
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
        
        # Get API version and base URL for Tooling API
        # Extract API version from base_url (e.g., https://xxx.salesforce.com/services/data/v58.0)
        try:
            # simple-salesforce stores the full base_url with version
            base_url_parts = self.sf.base_url.split('/services/data/')
            if len(base_url_parts) > 1:
                self.api_version = base_url_parts[1].split('/')[0]  # Extract version like "v58.0"
                self.base_url = base_url_parts[0]  # Base URL without /services/data
            else:
                # Fallback
                self.api_version = "v58.0"
                self.base_url = self.sf.base_url.replace('/services/data', '')
        except:
            # Fallback if parsing fails
            self.api_version = "v58.0"
            self.base_url = self.sf.base_url.replace('/services/data', '')
        
        self.session_id = self.sf.session_id
        print(f"  Using API version: {self.api_version}")
        
        # Track what exists
        self.existing_objects = self._get_existing_objects()
        self.existing_fields = {}  # Will be populated per object
        self.nonexistent_objects = set()  # Track objects that don't exist to avoid repeated warnings
        
        print(f"✅ Connected! Found {len(self.existing_objects)} objects in org")
        if dry_run:
            print("🔍 DRY RUN MODE - No changes will be made\n")
    
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
    
    def _get_existing_objects(self) -> Set[str]:
        """Get list of existing objects in the org."""
        try:
            describe_global = self.sf.describe()
            return {obj['name'] for obj in describe_global['sobjects']}
        except Exception as e:
            print(f"⚠️  Warning: Could not fetch existing objects: {e}")
            return set()
    
    def _get_existing_fields(self, object_name: str) -> Set[str]:
        """Get list of existing fields for an object."""
        # If we already know this object doesn't exist, return empty set without warning
        if object_name in self.nonexistent_objects:
            return set()
        
        # If we've already fetched fields for this object, return cached result
        if object_name in self.existing_fields:
            return self.existing_fields[object_name]
        
        # Check if object exists before trying to describe it
        if object_name not in self.existing_objects:
            # Object doesn't exist - cache this and return empty set
            self.nonexistent_objects.add(object_name)
            # Suppress warning for custom objects (they'll be created) - they're expected to not exist
            # Only show warning for standard objects that should exist
            if not object_name.endswith("__c"):
                # This is a standard object that should exist - show warning
                print(f"⚠️  Note: Object {object_name} does not exist in org (may need to be enabled)")
            return set()
        
        try:
            describe_result = self.sf.__getattr__(object_name).describe()
            fields = {field['name'] for field in describe_result['fields']}
            self.existing_fields[object_name] = fields
            return fields
        except Exception as e:
            # If object lookup fails, mark it as nonexistent to avoid repeated warnings
            error_str = str(e)
            if "NOT_FOUND" in error_str or "does not exist" in error_str.lower():
                # Suppress warning for custom objects that will be created (they're expected to not exist)
                # Only show warning for standard objects that should exist
                if not object_name.endswith("__c") and object_name not in self.nonexistent_objects:
                    print(f"⚠️  Warning: Object {object_name} does not exist in org")
                self.nonexistent_objects.add(object_name)
            else:
                # For other errors, show warning (but only once)
                if object_name not in self.nonexistent_objects:
                    print(f"⚠️  Warning: Could not fetch fields for {object_name}: {e}")
                    self.nonexistent_objects.add(object_name)
            return set()
    
    def _create_object_via_metadata_api(self, object_name: str, label: str, plural_label: str) -> bool:
        """Create custom object using Metadata API SOAP endpoint."""
        # Metadata API SOAP endpoint - use version without 'v' prefix (e.g., 59.0 not v59.0)
        api_version_num = self.api_version.replace("v", "")
        metadata_url = f"{self.base_url}/services/Soap/m/{api_version_num}"
        
        soap_envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:met="http://soap.sforce.com/2006/04/metadata">
   <soapenv:Header>
      <met:SessionHeader>
         <met:sessionId>{self.session_id}</met:sessionId>
      </met:SessionHeader>
   </soapenv:Header>
   <soapenv:Body>
      <met:createMetadata>
         <met:metadata xsi:type="met:CustomObject" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <met:fullName>{object_name}</met:fullName>
            <met:label>{label}</met:label>
            <met:pluralLabel>{plural_label}</met:pluralLabel>
            <met:nameField>
               <met:label>Name</met:label>
               <met:type>Text</met:type>
            </met:nameField>
            <met:deploymentStatus>Deployed</met:deploymentStatus>
            <met:sharingModel>ReadWrite</met:sharingModel>
         </met:metadata>
      </met:createMetadata>
   </soapenv:Body>
</soapenv:Envelope>"""
        
        headers = {
            "Content-Type": "text/xml; charset=UTF-8",
            "SOAPAction": "createMetadata"
        }
        
        try:
            response = requests.post(metadata_url, headers=headers, data=soap_envelope)
            
            if response.status_code == 200:
                # Parse SOAP response
                root = ET.fromstring(response.text)
                # Check for success
                ns = {'soapenv': 'http://schemas.xmlsoap.org/soap/envelope/', 
                      'met': 'http://soap.sforce.com/2006/04/metadata'}
                result = root.find('.//met:result', ns)
                if result is not None:
                    success = result.find('met:success', ns)
                    if success is not None and success.text == 'true':
                        print(f"  ✅ Created custom object: {object_name}")
                        self.existing_objects.add(object_name)
                        time.sleep(2)
                        return True
                    else:
                        # Get error message
                        errors = result.findall('met:errors', ns)
                        error_msg = errors[0].find('met:message', ns).text if errors else "Unknown error"
                        print(f"  ❌ Failed to create {object_name}: {error_msg}")
                        return False
            else:
                # Check for SOAP fault
                if 'soapenv:Fault' in response.text or response.status_code != 200:
                    try:
                        root = ET.fromstring(response.text)
                        ns = {'soapenv': 'http://schemas.xmlsoap.org/soap/envelope/'}
                        fault = root.find('.//soapenv:Fault', ns)
                        if fault is not None:
                            faultstring = fault.find('soapenv:faultstring', ns)
                            faultcode = fault.find('soapenv:faultcode', ns)
                            error_msg = faultstring.text if faultstring is not None else "SOAP fault"
                            error_code = faultcode.text if faultcode is not None else ""
                            print(f"  ❌ Failed to create {object_name}: {error_code} - {error_msg}")
                            # Show full response for debugging
                            if len(response.text) < 500:
                                print(f"     Full response: {response.text}")
                            # If it's an authentication or permission issue, suggest manual creation
                            if "INVALID_SESSION" in error_code or "INSUFFICIENT_ACCESS" in error_code:
                                print(f"     Note: Your user may need 'Customize Application' permission")
                            return False
                    except Exception as parse_error:
                        print(f"  ❌ Failed to parse SOAP response: {parse_error}")
                    print(f"  ❌ SOAP request failed: {response.status_code}")
                    print(f"     Response preview: {response.text[:500]}")
                    return False
        except Exception as e:
            print(f"  ❌ Error creating {object_name} via SOAP: {str(e)[:150]}")
            return False
        
        soap_envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:met="http://soap.sforce.com/2006/04/metadata">
   <soapenv:Header>
      <met:SessionHeader>
         <met:sessionId>{self.session_id}</met:sessionId>
      </met:SessionHeader>
   </soapenv:Header>
   <soapenv:Body>
      <met:createMetadata>
         <met:metadata xsi:type="met:CustomObject" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <met:fullName>{object_name}</met:fullName>
            <met:label>{label}</met:label>
            <met:pluralLabel>{plural_label}</met:pluralLabel>
            <met:nameField>
               <met:label>Name</met:label>
               <met:type>Text</met:type>
            </met:nameField>
            <met:deploymentStatus>Deployed</met:deploymentStatus>
            <met:sharingModel>ReadWrite</met:sharingModel>
         </met:metadata>
      </met:createMetadata>
   </soapenv:Body>
</soapenv:Envelope>"""
        
        headers = {
            "Content-Type": "text/xml; charset=UTF-8",
            "SOAPAction": "createMetadata"
        }
        
        response = requests.post(metadata_url, headers=headers, data=soap_envelope)
        
        if response.status_code == 200:
            # Parse SOAP response
            root = ET.fromstring(response.text)
            # Check for success
            ns = {'soapenv': 'http://schemas.xmlsoap.org/soap/envelope/', 
                  'met': 'http://soap.sforce.com/2006/04/metadata'}
            result = root.find('.//met:result', ns)
            if result is not None:
                success = result.find('met:success', ns)
                if success is not None and success.text == 'true':
                    print(f"  ✅ Created custom object: {object_name}")
                    self.existing_objects.add(object_name)
                    time.sleep(2)
                    return True
                else:
                    # Get error message
                    errors = result.findall('met:errors', ns)
                    error_msg = errors[0].find('met:message', ns).text if errors else "Unknown error"
                    print(f"  ❌ Failed to create {object_name}: {error_msg}")
                    return False
        else:
            print(f"  ❌ SOAP request failed: {response.status_code} - {response.text[:200]}")
            return False
    
    def create_custom_object(self, object_name: str, label: str = None) -> bool:
        """Create a custom object in Salesforce."""
        if object_name in self.existing_objects:
            return True  # Already exists
        
        if self.dry_run:
            print(f"  [DRY RUN] Would create custom object: {object_name}")
            return True
        
        try:
            # Custom objects need to end with __c
            if not object_name.endswith("__c"):
                print(f"  ⚠️  Skipping {object_name} - not a custom object (must end with __c)")
                return False
            
            label = label or object_name.replace("__c", "").replace("_", " ")
            plural_label = label + "s" if not label.endswith("s") else label + "es"
            
            # Use Tooling API with MetadataContainer (proper way to create metadata)
            # Step 1: Create a MetadataContainer (name max 32 chars)
            timestamp = str(int(time.time()))[-6:]  # Last 6 digits
            container_name = f"CRMA_{object_name[:15]}_{timestamp}"[:32]  # Max 32 chars
            container_url = f"{self.base_url}/services/data/{self.api_version}/tooling/sobjects/MetadataContainer/"
            headers = {
                "Authorization": f"Bearer {self.session_id}",
                "Content-Type": "application/json"
            }
            
            container_payload = {"Name": container_name}
            container_response = requests.post(container_url, headers=headers, json=container_payload)
            
            if container_response.status_code not in [200, 201]:
                print(f"  ❌ Failed to create MetadataContainer: {container_response.text}")
                return False
            
            container_id = container_response.json().get("id")
            if not container_id:
                print(f"  ❌ Failed to get container ID: {container_response.text}")
                return False
            
            # Step 2: Create ApexClassMember with CustomObject metadata
            # Format the CustomObject as XML string
            custom_object_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<CustomObject xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>{object_name}</fullName>
    <label>{label}</label>
    <pluralLabel>{plural_label}</pluralLabel>
    <nameField>
        <label>Name</label>
        <type>Text</type>
    </nameField>
    <deploymentStatus>Deployed</deploymentStatus>
    <sharingModel>ReadWrite</sharingModel>
</CustomObject>"""
            
            # For CustomObject, we need to use CustomObjectMember
            # But CustomObjectMember might not exist - try using ApexClassMember with proper format
            # Actually, let's try creating it as an ApexClass first, then convert
            # Or use the MetadataContainerDeployRequest directly
            
            # Try using CustomObjectMember if it exists
            member_url = f"{self.base_url}/services/data/{self.api_version}/tooling/sobjects/CustomObjectMember/"
            member_payload = {
                "MetadataContainerId": container_id,
                "Content": custom_object_xml,
                "FullName": object_name
            }
            
            member_response = requests.post(member_url, headers=headers, json=member_payload)
            
            # If CustomObjectMember doesn't work, try Metadata API with zip deploy
            if member_response.status_code not in [200, 201]:
                # Clean up the failed container
                requests.delete(f"{container_url}{container_id}", headers=headers)
                
                # Fallback: Use Metadata API with zip file (proper approach)
                return self._create_object_via_metadata_api(object_name, label, plural_label)
            
            if member_response.status_code not in [200, 201]:
                print(f"  ❌ Failed to create metadata member: {member_response.text}")
                # Clean up container
                requests.delete(f"{container_url}{container_id}", headers=headers)
                return False
            
            # Step 3: Deploy the container
            deploy_url = f"{self.base_url}/services/data/{self.api_version}/tooling/sobjects/ContainerAsyncRequest/"
            deploy_payload = {
                "IsCheckOnly": False,
                "MetadataContainerId": container_id
            }
            
            deploy_response = requests.post(deploy_url, headers=headers, json=deploy_payload)
            
            if deploy_response.status_code not in [200, 201]:
                print(f"  ❌ Failed to deploy: {deploy_response.text}")
                return False
            
            deploy_id = deploy_response.json().get("id")
            
            # Step 4: Poll for deployment status
            status_url = f"{self.base_url}/services/data/{self.api_version}/tooling/sobjects/ContainerAsyncRequest/{deploy_id}"
            max_attempts = 10
            for attempt in range(max_attempts):
                time.sleep(2)
                status_response = requests.get(status_url, headers=headers)
                
                if status_response.status_code == 200:
                    status_data = status_response.json()
                    state = status_data.get("State")
                    
                    if state == "Completed":
                        if status_data.get("ErrorMsg"):
                            print(f"  ❌ Failed to create {object_name}: {status_data.get('ErrorMsg')}")
                            return False
                        else:
                            print(f"  ✅ Created custom object: {object_name}")
                            self.existing_objects.add(object_name)
                            time.sleep(2)
                            return True
                    elif state == "Failed":
                        print(f"  ❌ Failed to create {object_name}: {status_data.get('ErrorMsg', 'Deployment failed')}")
                        return False
                    # Otherwise, still in progress, continue polling
            
            print(f"  ⚠️  Deployment timeout for {object_name}")
            return False
                
        except Exception as e:
            print(f"  ❌ Error creating {object_name}: {e}")
            import traceback
            traceback.print_exc()
            return False
            # Use Metadata API deploy with zip file
            # Create temporary directory and files
            with tempfile.TemporaryDirectory() as temp_dir:
                # Create objects directory
                objects_dir = os.path.join(temp_dir, "objects")
                os.makedirs(objects_dir, exist_ok=True)
                
                # Create CustomObject XML
                custom_object_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<CustomObject xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>{object_name}</fullName>
    <label>{label}</label>
    <pluralLabel>{plural_label}</pluralLabel>
    <nameField>
        <label>Name</label>
        <type>Text</type>
    </nameField>
    <deploymentStatus>Deployed</deploymentStatus>
    <sharingModel>ReadWrite</sharingModel>
</CustomObject>"""
                
                # Write XML file
                xml_file = os.path.join(objects_dir, f"{object_name}.object")
                with open(xml_file, 'w') as f:
                    f.write(custom_object_xml)
                
                # Create package.xml
                api_version_num = self.api_version.replace("v", "").replace(".0", "")
                package_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Package xmlns="http://soap.sforce.com/2006/04/metadata">
    <types>
        <members>{object_name}</members>
        <name>CustomObject</name>
    </types>
    <version>{api_version_num}.0</version>
</Package>"""
                
                package_file = os.path.join(temp_dir, "package.xml")
                with open(package_file, 'w') as f:
                    f.write(package_xml)
                
                # Create zip file
                zip_path = os.path.join(temp_dir, "deploy.zip")
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    zipf.write(package_file, "package.xml")
                    zipf.write(xml_file, f"objects/{object_name}.object")
                
                # Deploy using Metadata API REST endpoint
                # The Metadata API requires the zip to be base64 encoded in JSON
                with open(zip_path, 'rb') as zip_file:
                    zip_data = zip_file.read()
                    zip_base64 = base64.b64encode(zip_data).decode('utf-8')
                
                deploy_url = f"{self.base_url}/services/data/{self.api_version}/metadata/deployRequest"
                headers = {
                    "Authorization": f"Bearer {self.session_id}",
                    "Content-Type": "application/json"
                }
                
                # Metadata API deploy request format
                deploy_payload = {
                    "ZipFile": zip_base64,
                    "DeployOptions": {
                        "allowMissingFiles": False,
                        "autoUpdatePackage": False,
                        "checkOnly": False,
                        "ignoreWarnings": False,
                        "performRetrieve": False,
                        "purgeOnDelete": False,
                        "rollbackOnError": True,
                        "runTests": [],
                        "singlePackage": True
                    }
                }
                
                response = requests.post(deploy_url, headers=headers, json=deploy_payload)
                
                if response.status_code in [200, 201]:
                    result = response.json()
                    # Check deployment status
                    if result.get("id"):
                        # Poll for deployment status
                        deploy_id = result["id"]
                        status_url = f"{self.base_url}/services/data/{self.api_version}/metadata/deployRequest/{deploy_id}"
                        
                        # Wait a bit and check status
                        time.sleep(2)
                        status_response = requests.get(status_url, headers={"Authorization": f"Bearer {self.session_id}"})
                        
                        if status_response.status_code == 200:
                            status_data = status_response.json()
                            if status_data.get("status") == "Succeeded":
                                print(f"  ✅ Created custom object: {object_name}")
                                self.existing_objects.add(object_name)
                                time.sleep(2)  # Wait for object to be available
                                return True
                            elif status_data.get("status") == "Failed":
                                errors = status_data.get("details", {}).get("componentFailures", [])
                                error_msg = errors[0].get("problem", "Unknown error") if errors else "Deployment failed"
                                print(f"  ❌ Failed to create {object_name}: {error_msg}")
                                return False
                            else:
                                # Still in progress, wait and check again
                                time.sleep(3)
                                status_response = requests.get(status_url, headers={"Authorization": f"Bearer {self.session_id}"})
                                if status_response.status_code == 200:
                                    status_data = status_response.json()
                                    if status_data.get("status") == "Succeeded":
                                        print(f"  ✅ Created custom object: {object_name}")
                                        self.existing_objects.add(object_name)
                                        time.sleep(2)
                                        return True
                                    else:
                                        print(f"  ❌ Failed to create {object_name}: {status_data.get('status', 'Unknown status')}")
                                        return False
                        else:
                            print(f"  ❌ Failed to check deployment status: {status_response.text}")
                            return False
                    else:
                        print(f"  ❌ Failed to create {object_name}: {response.text}")
                        return False
                else:
                    print(f"  ❌ Failed to create {object_name}: {response.text}")
                    return False
                
        except Exception as e:
            print(f"  ❌ Error creating {object_name}: {e}")
            return False
    
    def create_custom_field(self, object_name: str, field_name: str, field_info: Dict, 
                           description: str) -> bool:
        """Create a custom field on an object."""
        # Check if field already exists
        existing_fields = self._get_existing_fields(object_name)
        if field_name in existing_fields:
            return True  # Already exists
        
        # Skip standard fields (they already exist)
        if not field_name.endswith("__c") and object_name not in ["Issue__c", "CaseHistory__c"]:
            # This is likely a standard field
            return True
        
        # Infer field type (do this for both dry-run and actual run)
        field_metadata = infer_field_type(field_name, description, object_name)
        field_type = field_metadata["type"]
        
        if self.dry_run:
            # Show additional info for Lookup and Picklist fields
            type_display = field_type
            if field_type == "Lookup" and "referenceTo" in field_metadata:
                type_display = f"Lookup({field_metadata['referenceTo']})"
            elif field_type == "Picklist" and "valueSet" in field_metadata:
                values = field_metadata.get("valueSet", {}).get("valueSetDefinition", {}).get("value", [])
                if values:
                    value_names = [v.get("fullName", "") for v in values if isinstance(v, dict)]
                    if value_names:
                        type_display = f"Picklist[{', '.join(value_names[:3])}{'...' if len(value_names) > 3 else ''}]"
            print(f"    [DRY RUN] Would create field: {field_name} ({type_display})")
            return True
        
        try:
            
            # Tooling API format for CustomField: FullName at top, Metadata nested
            field_label = field_name.replace("__c", "").replace("_", " ")
            
            # Build Metadata object (nested)
            field_meta = {
                "type": field_type,
                "label": field_label
            }
            
            # Add type-specific properties to Metadata
            if field_type == "Text":
                field_meta["length"] = field_metadata.get("length", 255)
            elif field_type == "LongTextArea":
                field_meta["length"] = field_metadata.get("length", 32000)
                field_meta["visibleLines"] = field_metadata.get("visibleLines", 3)
            elif field_type == "Number":
                field_meta["precision"] = field_metadata.get("precision", 18)
                field_meta["scale"] = field_metadata.get("scale", 2)
            elif field_type == "Lookup":
                field_meta["referenceTo"] = field_metadata.get("referenceTo")
                field_meta["relationshipName"] = field_metadata.get("relationshipName")
            elif field_type == "Picklist":
                if "valueSet" in field_metadata:
                    field_meta["valueSet"] = field_metadata["valueSet"]
            
            # Tooling API payload: FullName at top, Metadata nested
            payload = {
                "FullName": f"{object_name}.{field_name}",
                "Metadata": field_meta
            }
            
            # Create field using Tooling API REST endpoint
            url = f"{self.base_url}/services/data/{self.api_version}/tooling/sobjects/CustomField/"
            headers = {
                "Authorization": f"Bearer {self.session_id}",
                "Content-Type": "application/json"
            }
            
            response = requests.post(url, headers=headers, json=payload)
            
            if response.status_code in [200, 201]:
                print(f"    ✅ Created field: {field_name} ({field_type})")
                # Update cache
                if object_name not in self.existing_fields:
                    self.existing_fields[object_name] = set()
                self.existing_fields[object_name].add(field_name)
                time.sleep(0.5)  # Small delay between field creations
                return True
            else:
                # Check if it's a duplicate (field already exists)
                error_text = response.text
                if "DUPLICATE_DEVELOPER_NAME" in error_text or "already exists" in error_text.lower():
                    print(f"    ℹ️  Field {field_name} already exists (skipping)")
                    # Update cache to mark as existing
                    if object_name not in self.existing_fields:
                        self.existing_fields[object_name] = set()
                    self.existing_fields[object_name].add(field_name)
                    return True  # Treat as success (already exists)
                else:
                    print(f"    ❌ Failed to create {field_name}: {response.text}")
                    return False
                
        except Exception as e:
            print(f"    ❌ Error creating {field_name}: {e}")
            return False
    
    def create_external_id_field(self, object_name: str) -> bool:
        """Create OriginalId__c External ID field on an object for upsert support."""
        field_name = "OriginalId__c"
        
        # Skip objects that don't support External ID or don't exist
        # Knowledge__kav doesn't support External ID on custom Text fields
        # We'll use UrlName for Knowledge articles instead
        if object_name == "Knowledge__kav":
            print(f"    ℹ️  Skipping - Knowledge__kav uses UrlName for upsert matching")
            return True
        
        # Skip Activity objects (Event and Task) - they don't support External ID fields via Tooling API
        # Event and Task are Activity objects with restrictions on custom field creation
        # Unlike Knowledge__kav which uses UrlName for upsert matching, Event and Task have no unique identifier
        # They will use insert (not upsert) in the upload script
        if object_name in ["Event", "Task"]:
            print(f"    ℹ️  Skipping - {object_name} (Activity object) doesn't support External ID fields via Tooling API")
            print(f"       Note: {object_name} will use insert (not upsert) since it has no unique identifier field")
            return True
        
        # Skip objects that require special features to be enabled
        if object_name in ["LiveChatTranscript", "ProductCategory", "ProductCategoryProduct"]:
            if object_name not in self.existing_objects:
                print(f"    ℹ️  Skipping - {object_name} not available in org")
                return True
        
        # Check if field already exists
        existing_fields = self._get_existing_fields(object_name)
        if field_name in existing_fields:
            print(f"    ℹ️  External ID field {field_name} already exists")
            return True
        
        if self.dry_run:
            print(f"    [DRY RUN] Would create External ID field: {field_name}")
            return True
        
        try:
            # Build Metadata for External ID field
            field_meta = {
                "type": "Text",
                "label": "Original ID",
                "length": 18,  # Salesforce IDs are 18 characters
                "externalId": True,  # This makes it an External ID field
                "unique": True  # External IDs should be unique
            }
            
            # Tooling API payload
            payload = {
                "FullName": f"{object_name}.{field_name}",
                "Metadata": field_meta
            }
            
            # Create field using Tooling API REST endpoint
            url = f"{self.base_url}/services/data/{self.api_version}/tooling/sobjects/CustomField/"
            headers = {
                "Authorization": f"Bearer {self.session_id}",
                "Content-Type": "application/json"
            }
            
            response = requests.post(url, headers=headers, json=payload)
            
            if response.status_code in [200, 201]:
                print(f"    ✅ Created External ID field: {field_name}")
                # Update cache
                if object_name not in self.existing_fields:
                    self.existing_fields[object_name] = set()
                self.existing_fields[object_name].add(field_name)
                time.sleep(0.5)
                return True
            else:
                error_msg = response.text
                if "DUPLICATE_DEVELOPER_NAME" in error_msg or "already exists" in error_msg.lower():
                    print(f"    ℹ️  External ID field {field_name} already exists")
                    return True
                # Check for entity not found errors or restricted picklist errors (Event/Task)
                if ("not found" in error_msg.lower() or 
                    "FIELD_INTEGRITY_EXCEPTION" in error_msg or
                    "INVALID_OR_NULL_FOR_RESTRICTED_PICKLIST" in error_msg or
                    "bad value for restricted picklist field" in error_msg.lower()):
                    print(f"    ℹ️  Skipping - {object_name} may not be available or doesn't support External ID")
                    return True
                print(f"    ❌ Failed to create External ID field {field_name}: {error_msg[:200]}")
                return False
                
        except Exception as e:
            print(f"    ❌ Error creating External ID field {field_name}: {e}")
            return False

    def sync_schema(self, schema_file: str, skip_existing: bool = True):
        """Sync schema from JSON file to Salesforce."""
        print(f"\n{'='*60}")
        print(f"Syncing schema from: {schema_file}")
        print(f"{'='*60}\n")
        
        # Load schema
        with open(schema_file, 'r') as f:
            schema = json.load(f)
        
        stats = {
            "objects_created": 0,
            "objects_skipped": 0,
            "fields_created": 0,
            "fields_skipped": 0,
            "errors": 0
        }
        
        # Store field definitions for second pass
        field_definitions = []  # List of (object_name, field_name, field_description)
        
        # PASS 1: Create all custom objects first
        print("📦 Phase 1: Creating custom objects...\n")
        for obj_def in schema:
            object_name = obj_def.get("object")
            fields = obj_def.get("fields", {})
            
            # Check if it's a custom object
            is_custom = object_name.endswith("__c")
            
            if is_custom and object_name not in self.existing_objects:
                print(f"📋 Processing object: {object_name}")
                # Create custom object
                if self.create_custom_object(object_name):
                    stats["objects_created"] += 1
                else:
                    stats["errors"] += 1
                    continue
            elif is_custom:
                print(f"📋 Processing object: {object_name}")
                print(f"  ℹ️  Custom object {object_name} already exists")
                stats["objects_skipped"] += 1
            
            # Store field definitions for second pass
            for field_name, field_description in fields.items():
                # Skip standard fields on standard objects
                if not is_custom and not field_name.endswith("__c"):
                    continue
                field_definitions.append((object_name, field_name, field_description))
        
        # Wait a bit for objects to be fully available and refresh cache
        if stats["objects_created"] > 0:
            print(f"\n⏳ Waiting for objects to be fully available...")
            time.sleep(3)
            # Refresh existing objects cache to include newly created objects
            self.existing_objects = self._get_existing_objects()
            print(f"✅ Refreshed object cache: {len(self.existing_objects)} objects now available\n")
        
        # PASS 2: Create all fields (now that all objects exist)
        print(f"\n📝 Phase 2: Creating custom fields...\n")
        current_object = None
        for object_name, field_name, field_description in field_definitions:
            field_info = {"description": field_description}
            
            # Show object name when we start processing a new object
            if object_name != current_object:
                print(f"📋 Processing object: {object_name}")
                current_object = object_name
            
            if self.create_custom_field(object_name, field_name, field_info, field_description):
                stats["fields_created"] += 1
            else:
                # Check if it's a dependency issue (object doesn't exist yet)
                field_metadata = infer_field_type(field_name, field_description, object_name)
                if field_metadata.get("type") == "Lookup":
                    ref_obj = field_metadata.get("referenceTo")
                    if ref_obj and ref_obj.endswith("__c") and ref_obj not in self.existing_objects:
                        # Referenced object doesn't exist - this shouldn't happen after pass 1,
                        # but if it does, mark as error
                        stats["errors"] += 1
                        print(f"    ⚠️  Skipping {field_name}: Referenced object {ref_obj} not found")
                        stats["fields_skipped"] += 1
                        continue
                
                stats["fields_skipped"] += 1
                stats["errors"] += 1
        
        # PASS 3: Create OriginalId__c External ID field on all objects (for upsert support)
        print(f"\n🔑 Phase 3: Creating OriginalId__c External ID fields for upsert support...\n")
        
        # Get all objects that were processed (both custom and standard that have custom fields)
        objects_to_process = set()
        for obj_def in schema:
            objects_to_process.add(obj_def.get("object"))
        
        external_id_created = 0
        external_id_skipped = 0
        
        for object_name in sorted(objects_to_process):
            print(f"  📋 {object_name}")
            if self.create_external_id_field(object_name):
                external_id_created += 1
            else:
                external_id_skipped += 1
        
        stats["external_id_created"] = external_id_created
        stats["external_id_skipped"] = external_id_skipped
        
        # Print summary
        print(f"\n{'='*60}")
        print("Sync Summary")
        print(f"{'='*60}")
        print(f"Objects created: {stats['objects_created']}")
        print(f"Objects skipped: {stats['objects_skipped']}")
        print(f"Fields created: {stats['fields_created']}")
        print(f"Fields skipped: {stats['fields_skipped']}")
        print(f"External ID fields created: {stats.get('external_id_created', 0)}")
        if stats['errors'] > 0:
            print(f"Errors: {stats['errors']}")
        print(f"{'='*60}\n")
        
        if self.dry_run:
            print("🔍 This was a DRY RUN - no actual changes were made")
            print("   Run without --dry-run to apply changes\n")

def main():
    parser = argparse.ArgumentParser(
        description="Sync CRMArena schema to Salesforce Developer org"
    )
    parser.add_argument(
        "--org_type",
        type=str,
        default="original",
        choices=["original", "b2b", "b2c"],
        help="Organization type"
    )
    parser.add_argument(
        "--schema_file",
        type=str,
        default=None,
        help="Path to schema JSON file (default: schema_exports/{org_type}_schema.json)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them"
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip objects/fields that already exist (default: True)"
    )
    
    args = parser.parse_args()
    
    # Determine schema file
    if args.schema_file:
        schema_file = args.schema_file
    else:
        # Schema file path (relative to CRMArena root or etl folder)
        schema_file = f"../schema_exports/{args.org_type}_schema.json"
        if not os.path.exists(schema_file):
            # Try from CRMArena root (if running from there)
            schema_file = f"schema_exports/{args.org_type}_schema.json"
    
    if not os.path.exists(schema_file):
        print(f"❌ Error: Schema file not found: {schema_file}")
        print(f"   Run 'python export_schema.py --org_type {args.org_type}' first")
        return 1
    
    try:
        syncer = SchemaSyncer(org_type=args.org_type, dry_run=args.dry_run)
        syncer.sync_schema(schema_file, skip_existing=args.skip_existing)
        return 0
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())

