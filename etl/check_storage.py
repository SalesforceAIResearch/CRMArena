#!/usr/bin/env python3
"""Check Salesforce org storage and record counts."""

from simple_salesforce import Salesforce
from dotenv import load_dotenv
import os

# Load .env from parent directory (CRMArena root) or current directory
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()  # Fallback to default search

sf = Salesforce(
    username=os.getenv('SALESFORCE_USERNAME'),
    password=os.getenv('SALESFORCE_PASSWORD'),
    security_token=os.getenv('SALESFORCE_SECURITY_TOKEN')
)

print("Checking Salesforce org storage and record counts...\n")

# Check object record counts
objects_to_check = [
    'Account', 'Contact', 'Case', 'Product2', 'Order', 'OrderItem', 
    'PricebookEntry', 'EmailMessage', 'CaseHistory__c', 'Knowledge__kav',
    'Issue__c', 'Pricebook2'
]

total_records = 0
print("Record counts by object:")
print("-" * 40)

for obj in objects_to_check:
    try:
        count_result = sf.query(f'SELECT COUNT() FROM {obj}')
        count = count_result['totalSize']
        if count > 0:
            print(f"  {obj:20s}: {count:>8,} records")
            total_records += count
    except Exception as e:
        # Object might not exist or no access
        pass

print("-" * 40)
print(f"  {'Total':20s}: {total_records:>8,} records")
print("\n💡 Tip: Delete records using cleanup_salesforce_data.py")
print("   Example: python cleanup_salesforce_data.py --org_type original --object CaseHistory__c --confirm")

