#!/usr/bin/env python3
"""
Test connection to scratch org using different authentication methods.
"""

import os
import subprocess
import json
from dotenv import load_dotenv
from simple_salesforce import Salesforce

def get_access_token_from_cli():
    """Get access token from Salesforce CLI."""
    try:
        result = subprocess.run(
            ['sf', 'org', 'display', '--target-org', 'crmarena-1765904226', '--json'],
            capture_output=True,
            text=True,
            check=True
        )
        data = json.loads(result.stdout)
        access_token = data.get('result', {}).get('accessToken', '')
        instance_url = data.get('result', {}).get('instanceUrl', '')
        return access_token, instance_url
    except Exception as e:
        print(f"❌ Could not get access token from CLI: {e}")
        return None, None

def test_with_access_token():
    """Test connection using access token from CLI."""
    print("\n" + "="*60)
    print("Method 1: Using Access Token from Salesforce CLI")
    print("="*60)
    
    access_token, instance_url = get_access_token_from_cli()
    
    if not access_token:
        print("❌ Could not get access token")
        return False
    
    try:
        # Use the full instance URL with access token
        # simple-salesforce needs instance_url and session_id
        from simple_salesforce import Salesforce
        
        # Extract domain from instance URL
        # e.g., https://app-customization-6035.scratch.my.salesforce.com
        # -> app-customization-6035.scratch.my.salesforce.com
        domain = instance_url.replace('https://', '')
        
        sf = Salesforce(instance_url=instance_url, session_id=access_token)
        print(f"✅ Connected successfully using access token!")
        print(f"   Instance URL: {instance_url}")
        
        # Test query
        result = sf.query("SELECT Id, Name FROM Account LIMIT 1")
        print(f"   Test query successful: {result['totalSize']} records")
        return True
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_with_username_password():
    """Test connection using username/password from .env."""
    print("\n" + "="*60)
    print("Method 2: Using Username/Password from .env")
    print("="*60)
    
    # Load .env from parent directory (CRMArena root) or current directory
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
    else:
        load_dotenv()  # Fallback to default search
    username = os.getenv('SALESFORCE_USERNAME')
    password = os.getenv('SALESFORCE_PASSWORD')
    security_token = os.getenv('SALESFORCE_SECURITY_TOKEN')
    
    print(f"Username: {username}")
    print(f"Password: {'***' if password else 'NOT SET'}")
    print(f"Security Token: {'***' if security_token else 'NOT SET'}")
    
    if not username or not password:
        print("❌ Username or password not set in .env")
        return False
    
    try:
        if security_token:
            sf = Salesforce(username=username, password=password, security_token=security_token)
        else:
            # Try without token (for some orgs)
            sf = Salesforce(username=username, password=password)
        
        print(f"✅ Connected successfully!")
        print(f"   Instance URL: {sf.sf_instance}")
        
        # Test query
        result = sf.query("SELECT Id, Name FROM Account LIMIT 1")
        print(f"   Test query successful: {result['totalSize']} records")
        return True
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        print("\n💡 Solutions:")
        print("   1. Reset security token in Salesforce UI:")
        print("      - Open org: sf org open --target-org crmarena-1765904226")
        print("      - Go to: Setup → My Personal Information → Reset My Security Token")
        print("   2. Or use the access token method (Method 1) instead")
        return False

if __name__ == "__main__":
    print("="*60)
    print("Testing Scratch Org Connection")
    print("="*60)
    
    # Try access token first (most reliable for scratch orgs)
    success = test_with_access_token()
    
    if not success:
        # Fall back to username/password
        test_with_username_password()
    
    print("\n" + "="*60)
    if success:
        print("✅ Connection successful! You can use this method for uploads.")
    else:
        print("❌ Connection failed. See solutions above.")
    print("="*60)

