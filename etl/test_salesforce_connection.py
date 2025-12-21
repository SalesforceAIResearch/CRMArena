#!/usr/bin/env python3
"""
Test script to verify Salesforce connection and credentials.
Run this to diagnose authentication issues.
"""

from dotenv import load_dotenv
import os
from simple_salesforce import Salesforce

def test_salesforce_connection(org_type="original"):
    """Test Salesforce connection for a given org type."""
    # Load .env from parent directory (CRMArena root) or current directory
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
    else:
        load_dotenv()  # Fallback to default search
    
    print(f"\n{'='*60}")
    print(f"Testing Salesforce Connection for: {org_type}")
    print(f"{'='*60}\n")
    
    # Get credentials based on org_type
    if org_type == "b2b":
        username = os.getenv("SALESFORCE_B2B_USERNAME")
        password = os.getenv("SALESFORCE_B2B_PASSWORD")
        security_token = os.getenv("SALESFORCE_B2B_SECURITY_TOKEN")
        env_vars = ["SALESFORCE_B2B_USERNAME", "SALESFORCE_B2B_PASSWORD", "SALESFORCE_B2B_SECURITY_TOKEN"]
    elif org_type == "b2c":
        username = os.getenv("SALESFORCE_B2C_USERNAME")
        password = os.getenv("SALESFORCE_B2C_PASSWORD")
        security_token = os.getenv("SALESFORCE_B2C_SECURITY_TOKEN")
        env_vars = ["SALESFORCE_B2C_USERNAME", "SALESFORCE_B2C_PASSWORD", "SALESFORCE_B2C_SECURITY_TOKEN"]
    else:  # original
        username = os.getenv("SALESFORCE_USERNAME")
        password = os.getenv("SALESFORCE_PASSWORD")
        security_token = os.getenv("SALESFORCE_SECURITY_TOKEN")
        env_vars = ["SALESFORCE_USERNAME", "SALESFORCE_PASSWORD", "SALESFORCE_SECURITY_TOKEN"]
    
    # Check if credentials are loaded
    print("Checking environment variables...")
    all_present = True
    for var in env_vars:
        value = os.getenv(var)
        if value:
            # Mask sensitive values
            if "PASSWORD" in var or "TOKEN" in var:
                display_value = value[:4] + "..." if len(value) > 4 else "***"
            else:
                display_value = value
            print(f"  ✓ {var}: {display_value}")
        else:
            print(f"  ✗ {var}: NOT FOUND")
            all_present = False
    
    if not all_present:
        print("\n❌ Error: Some credentials are missing from environment variables!")
        print("   Make sure your .env file is in the CRMArena directory and contains all required variables.")
        return False
    
    # Try to connect
    print("\nAttempting to connect to Salesforce...")
    try:
        sf = Salesforce(
            username=username,
            password=password,
            security_token=security_token
        )
        print("✅ Successfully connected to Salesforce!")
        
        # Try a simple query to verify access
        print("\nTesting query access...")
        result = sf.query("SELECT Id, Name FROM User LIMIT 1")
        if result['records']:
            print(f"✅ Query successful! Found user: {result['records'][0].get('Name', 'N/A')}")
        else:
            print("⚠️  Query returned no results (but connection worked)")
        
        return True
        
    except Exception as e:
        error_msg = str(e)
        print(f"\n❌ Connection failed!")
        print(f"   Error: {error_msg}")
        
        if "INVALID_LOGIN" in error_msg:
            print("\n💡 Troubleshooting tips:")
            print("   1. Verify credentials are correct in your .env file")
            print("   2. Try logging into Salesforce via web browser:")
            print("      https://login.salesforce.com/")
            print("   3. Security tokens can expire - you may need to reset it")
            print("   4. The test account may be locked - contact CRMArena maintainers")
            print("   5. If using your own org, make sure the credentials are correct")
        elif "TIMEOUT" in error_msg or "Connection" in error_msg:
            print("\n💡 Troubleshooting tips:")
            print("   1. Check your internet connection")
            print("   2. Verify you can access login.salesforce.com in a browser")
            print("   3. Check if there are firewall/proxy issues")
        
        return False

if __name__ == "__main__":
    import sys
    
    org_type = sys.argv[1] if len(sys.argv) > 1 else "original"
    
    if org_type not in ["original", "b2b", "b2c"]:
        print(f"Error: Invalid org_type '{org_type}'. Must be 'original', 'b2b', or 'b2c'")
        sys.exit(1)
    
    success = test_salesforce_connection(org_type)
    sys.exit(0 if success else 1)

