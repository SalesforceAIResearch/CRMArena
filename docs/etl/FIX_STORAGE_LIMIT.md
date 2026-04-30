# Fixing "Storage Limit Exceeded" Error

Salesforce Developer orgs have limited storage (typically 5MB data + 20MB files). If you see "storage limit exceeded" errors, you need to free up space.

## Option 1: Check Current Storage Usage

```bash
cd /Users/tarunanand/Benchmarks/CRMArena
source venv/bin/activate
python -c "
from simple_salesforce import Salesforce
from dotenv import load_dotenv
import os

load_dotenv()
sf = Salesforce(
    username=os.getenv('SALESFORCE_USERNAME'),
    password=os.getenv('SALESFORCE_PASSWORD'),
    security_token=os.getenv('SALESFORCE_SECURITY_TOKEN')
)

# Check storage
result = sf.query('SELECT DataStorageMB, FileStorageMB FROM Organization LIMIT 1')
if result['records']:
    org = result['records'][0]
    print(f'Data Storage: {org.get(\"DataStorageMB\", \"N/A\")} MB')
    print(f'File Storage: {org.get(\"FileStorageMB\", \"N/A\")} MB')
"
```

## Option 2: Delete Existing Data (Recommended)

Use the cleanup script to delete data:

### Delete All Objects (Dry Run First)

```bash
# Dry run - see what would be deleted
python cleanup_salesforce_data.py --org_type original --all-objects

# Actually delete (be careful!)
python cleanup_salesforce_data.py --org_type original --all-objects --confirm
```

### Delete Specific Object

```bash
# Delete Account records (dry run)
python cleanup_salesforce_data.py --org_type original --object Account

# Delete Account records (actually delete)
python cleanup_salesforce_data.py --org_type original --object Account --confirm

# Delete with limit
python cleanup_salesforce_data.py --org_type original --object Account --limit 100 --confirm
```

### Delete Large Objects First

Objects that typically use the most storage:
1. **CaseHistory__c** - History records
2. **EmailMessage** - Email attachments
3. **OrderItem** - Many records per order
4. **Case** - Case records

```bash
# Delete history records first
python cleanup_salesforce_data.py --org_type original --object CaseHistory__c --confirm

# Delete email messages
python cleanup_salesforce_data.py --org_type original --object EmailMessage --confirm
```

## Option 3: Upload with Limits

Instead of deleting, upload fewer records:

```bash
# Upload only 10 records per object
python upload_data_to_salesforce.py --org_type original --skip User ProductCategory ProductCategoryProduct LiveChatTranscript --limit 10
```

## Option 4: Manual Cleanup via Salesforce UI

1. **Go to Setup** → **Data Management** → **Storage Usage**
2. See which objects use the most space
3. **Delete records manually**:
   - Go to the object (e.g., Account, Case)
   - Use list view to select records
   - Delete in batches

## Option 5: Delete via SOQL (Advanced)

```bash
# Delete all CaseHistory__c records
python -c "
from simple_salesforce import Salesforce
from dotenv import load_dotenv
import os

load_dotenv()
sf = Salesforce(
    username=os.getenv('SALESFORCE_USERNAME'),
    password=os.getenv('SALESFORCE_PASSWORD'),
    security_token=os.getenv('SALESFORCE_SECURITY_TOKEN')
)

# Query and delete
result = sf.query('SELECT Id FROM CaseHistory__c LIMIT 1000')
ids = [r['Id'] for r in result['records']]
if ids:
    delete_results = sf.bulk.CaseHistory__c.delete(ids)
    print(f'Deleted {len([r for r in delete_results if r[\"success\"]])} records')
"
```

## Recommended Cleanup Order

Delete objects in this order (reverse of upload order):

1. CaseHistory__c (history records)
2. EmailMessage (email records)
3. Knowledge__kav (knowledge articles)
4. OrderItem (order line items)
5. Order (orders)
6. Case (cases)
7. PricebookEntry (pricebook entries)
8. Contact (contacts)
9. Product2 (products)
10. Account (accounts)

## After Cleanup

1. **Verify storage is freed**:
   ```bash
   # Check storage again
   python -c "..." # (use the check script above)
   ```

2. **Re-run upload**:
   ```bash
   python upload_data_to_salesforce.py --org_type original --skip User ProductCategory ProductCategoryProduct LiveChatTranscript
   ```

## Prevention

To avoid storage issues:
- Use `--limit` when testing
- Delete old test data regularly
- Focus on essential objects only
- Consider using a Production org or Sandbox with more storage

## Developer Org Limits

- **Data Storage**: 5 MB
- **File Storage**: 20 MB
- **Total Records**: ~10,000-50,000 (depending on field sizes)

If you consistently hit limits, consider:
- Upgrading to a paid org
- Using a Sandbox with more storage
- Cleaning up data more frequently

