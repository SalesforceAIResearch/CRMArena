# Enabling ProductCategory in Salesforce

ProductCategory records require a **Catalog** object to exist. Catalogs are used in Salesforce B2B Commerce (formerly CloudCraze) to organize products.

## Option 1: Create a Default Catalog (Recommended)

If you want to upload ProductCategory records, you'll need to create at least one Catalog first.

### Using Salesforce UI:

1. **Navigate to Setup**:
   - Click the gear icon (⚙️) → **Setup**

2. **Enable B2B Commerce** (if not already enabled):
   - In Quick Find, search for: `B2B Commerce`
   - Follow the setup wizard if prompted
   - Note: B2B Commerce may require additional licenses

3. **Create a Catalog**:
   - Navigate to: **Commerce** → **Catalogs** (or **B2B Commerce** → **Catalogs`)
   - Click **New Catalog**
   - Fill in:
     - **Name**: "Default Catalog" (or any name)
     - **Active**: Check this box
   - Click **Save**

4. **Note the Catalog ID**:
   - After creating, note the Catalog ID (starts with `0ZG...`)
   - You may need to update the script to use this Catalog ID

### Using API (if B2B Commerce is enabled):

You can create a Catalog via API if you have the right permissions:

```python
# Example: Create a Catalog
catalog = {
    "Name": "Default Catalog",
    "IsActive": True
}
result = sf.Catalog__c.create(catalog)
```

**Note**: The Catalog object name may vary depending on your Salesforce edition:
- `Catalog__c` (custom object in some orgs)
- `Catalog` (standard object in B2B Commerce)

## Option 2: Skip ProductCategory (Simpler)

If you don't need ProductCategory records, you can skip them:

```bash
python upload_data_to_salesforce.py --org_type original --skip ProductCategory
```

## Option 3: Modify Script to Create Default Catalog

The script could be enhanced to:
1. Check if any Catalog exists
2. Create a default Catalog if none exists
3. Use that Catalog ID for all ProductCategory records

This would require:
- B2B Commerce to be enabled
- Appropriate API permissions
- Knowledge of the Catalog object API name in your org

## Current Status

**B2B Commerce Check**: 
- ❌ B2B Commerce does not appear to be enabled in your Developer org
- ❌ Catalog object is not available
- ⚠️ ProductCategory requires CatalogId (which requires a Catalog object)

The upload script currently:
- ✅ Detects when CatalogId is missing
- ✅ Provides clear error messages
- ✅ Skips ProductCategory records gracefully
- ⚠️ Does not automatically create a Catalog (requires B2B Commerce)

## Recommendation

For a Developer org, **skipping ProductCategory is recommended** unless you specifically need it:

```bash
python upload_data_to_salesforce.py --org_type original --skip ProductCategory
```

If you need ProductCategory:
1. Enable B2B Commerce in your org (may require additional setup/licenses)
2. Create a Catalog through the UI
3. Re-run the upload

## Troubleshooting

### Error: "invalid cross reference id"
- **Cause**: The CatalogId in the data doesn't exist in your org
- **Solution**: Create a Catalog first, or skip ProductCategory records

### Error: "Object 'Catalog' does not exist"
- **Cause**: B2B Commerce is not enabled in your org
- **Solution**: Enable B2B Commerce, or skip ProductCategory

### Error: "REQUIRED_FIELD_MISSING: CatalogId"
- **Cause**: ProductCategory requires CatalogId but it's not provided
- **Solution**: The script should skip these records automatically

## Next Steps

1. **Check if B2B Commerce is enabled** in your org
2. **Create a Catalog** if needed
3. **Update the script** to use the new Catalog ID (or modify to auto-create)
4. **Re-run the upload** for ProductCategory

