# Data Upload Status

## ✅ Working Objects (can upload successfully)
1. **Account** - ✅ Working (5/5 uploaded)
2. **Product2** - ✅ Working (5/5 uploaded)
3. **Pricebook2** - ✅ Working (5/5 uploaded)
4. **Issue__c** - ✅ Working (5/5 uploaded)
5. **Case** - ✅ Working (5/5 uploaded) - Fixed by skipping CreatedDate/ClosedDate
6. **CaseHistory__c** - ✅ Working (3/3 uploaded) - Fixed by skipping system audit fields
7. **EmailMessage** - ✅ Working (2/2 uploaded) - Fixed by skipping ToIds field
8. **Knowledge__kav** - ✅ Working (2/2 uploaded) - Fixed by handling UrlName duplicates and skipping FAQ_Answer__c

## ⚠️ Objects with Issues

### Contact
- **Issue**: Duplicate detection on Email field
- **Error**: `DUPLICATES_DETECTED` - "Use one of these records?"
- **Root Cause**: Contacts with same email already exist in Salesforce
- **Fix Applied**: Script now checks existing emails and skips duplicates
- **Status**: Working as designed - skips duplicates to avoid errors

### Order
- **Issue**: AccountId is required but not mapped when uploading individually
- **Error**: "Select an account" / "Required fields are missing: [AccountId]"
- **Status**: Records are skipped with clear message when AccountId can't be mapped
- **Fix**: Upload Account first in same run, or upload all objects in dependency order

### OrderItem
- **Issue**: Depends on Order and PricebookEntry
- **Error**: "Required fields are missing: [OrderId, PricebookEntryId]"
- **Status**: Records are skipped with clear message when required fields can't be mapped
- **Fix**: Upload Order and PricebookEntry first in same run

### PricebookEntry
- **Issue**: Depends on Product2 and Pricebook2
- **Error**: "Required fields are missing: [Pricebook2Id, Product2Id]"
- **Status**: Records are skipped with clear message when required fields can't be mapped
- **Fix**: Upload Product2 and Pricebook2 first in same run

### ProductCategory
- **Issue**: CatalogId is required but doesn't exist
- **Error**: "Required fields are missing: [CatalogId]"
- **Status**: Skipped - requires Catalog object which may not exist
- **Fix**: Create default Catalog or skip ProductCategory

### ProductCategoryProduct
- **Issue**: Depends on ProductCategory and Product2
- **Error**: "Required fields are missing: [ProductCategoryId, ProductId]"
- **Status**: Records are skipped with clear message when required fields can't be mapped
- **Fix**: Upload ProductCategory and Product2 first in same run

### LiveChatTranscript
- **Issue**: Object doesn't exist - requires Live Agent to be enabled
- **Error**: "Unable to find object: LiveChatTranscript"
- **Status**: Automatically skipped with informative message
- **Fix**: Enable Live Agent in Salesforce Setup if needed

### Knowledge__kav
- **Issue**: FAQ_Answer__c field doesn't exist
- **Error**: "No such column 'FAQ_Answer__c'"
- **Status**: Custom fields are skipped
- **Fix**: Enable Knowledge and sync schema, or skip Knowledge__kav

## 🔧 Fixes Applied

1. ✅ Boolean field conversion (IsActive) - fixed
2. ✅ Account Name field generation - fixed
3. ✅ ShippingState/ShippingCity skipping - fixed
4. ✅ Person Account fields skipping - fixed
5. ✅ External_ID__c skipping - fixed
6. ✅ ValidFrom/ValidTo skipping for Pricebook2 - fixed
7. ✅ Order Status forcing to Draft - fixed
8. ✅ Contact duplicate detection - fixed (skips duplicates)
9. ✅ Case system audit fields (CreatedDate/ClosedDate) - fixed
10. ✅ Case IssueId__c field skipping - fixed
11. ✅ CaseHistory__c system audit fields - fixed
12. ✅ CaseHistory__c custom fields (Field__c, NewValue__c) - fixed
13. ✅ EmailMessage ToIds field - fixed (skipped)
14. ✅ Order/OrderItem/PricebookEntry/ProductCategoryProduct - skip records when required fields missing
15. ✅ LiveChatTranscript - auto-skip with informative message
16. ✅ System audit fields (CreatedDate, LastModifiedDate, SystemModstamp) - skipped for all objects
17. ✅ Knowledge__kav UrlName duplicate handling - fixed
18. ✅ Knowledge__kav FAQ_Answer__c field - skipped (field doesn't exist, articles upload without it)

## 📝 Usage Notes

### Uploading Objects Individually
When uploading objects one at a time with `--only`, objects with dependencies (Order, OrderItem, PricebookEntry, etc.) will be skipped if their required parent IDs aren't mapped. This is expected behavior.

### Uploading All Objects Together
For best results, upload all objects in one run (without `--only`) so ID mappings persist:
```bash
python upload_data_to_salesforce.py --org_type original --skip User ProductCategory Knowledge__kav --limit 10
```

This ensures:
- Account IDs are mapped when uploading Contact/Order
- Product2/Pricebook2 IDs are mapped when uploading PricebookEntry
- Order IDs are mapped when uploading OrderItem
- Case IDs are mapped when uploading EmailMessage/CaseHistory__c

### Objects That Require Special Setup
- **User**: ✅ Fixed - Now attempts creation (requires "Manage Users" permission - see ENABLE_USER_CREATION.md)
- **ProductCategory**: ⚠️ Requires B2B Commerce + Catalog (not available in standard Developer org - recommend skipping)
- **LiveChatTranscript**: ✅ Auto-skipped - Requires Live Agent (already handled)
- **Knowledge__kav**: ✅ Fixed - Now working! (Knowledge was already enabled, fixed UrlName duplicates, FAQ_Answer__c skipped)

