# Automated Schema Sync Guide

This guide explains how to automatically sync the CRMArena schema to your Salesforce Developer org.

## Overview

The `sync_schema_to_salesforce.py` script automatically:
1. Reads the exported schema JSON file
2. Creates custom objects (like `Issue__c`, `CaseHistory__c`)
3. Creates custom fields on standard and custom objects
4. Sets up relationships between objects

## Prerequisites

1. **Salesforce Developer Org**: You need a Salesforce Developer Edition account
   - Sign up at: https://developer.salesforce.com/signup
   - Get your security token (see `SALESFORCE_CREDENTIALS_SETUP.md`)

2. **Environment Setup**:
   - Your `.env` file configured with Salesforce credentials
   - Python virtual environment activated
   - Schema exported (run `export_schema.py` first)

## Step-by-Step Instructions

### Step 1: Export the Schema

First, export the schema you want to sync:

```bash
cd /Users/tarunanand/Benchmarks/CRMArena
source venv/bin/activate
python export_schema.py --org_type original
```

This creates `schema_exports/original_schema.json`

### Step 2: Test Your Connection

Verify your Salesforce credentials work:

```bash
python test_salesforce_connection.py original
```

You should see:
```
✅ Successfully connected to Salesforce!
✅ Query successful!
```

### Step 3: Preview Changes (Dry Run)

Before making actual changes, preview what will be created:

```bash
python sync_schema_to_salesforce.py --org_type original --dry-run
```

This shows you:
- Which custom objects will be created
- Which custom fields will be created
- What field types will be used

**No changes are made** in dry-run mode.

### Step 4: Sync the Schema

Once you're satisfied with the preview, run the actual sync:

```bash
python sync_schema_to_salesforce.py --org_type original
```

The script will:
- Create custom objects (`Issue__c`, `CaseHistory__c`)
- Create custom fields on standard objects (e.g., `IssueId__c`, `OrderItemId__c` on `Case`)
- Create fields on custom objects
- Skip objects/fields that already exist

### Step 5: Verify in Salesforce

Log into your Salesforce org and verify:
1. **Custom Objects**: Setup → Object Manager → Check for `Issue` and `Case History`
2. **Custom Fields**: 
   - Go to any object (e.g., Case)
   - Check Fields & Relationships
   - Verify custom fields were created

## Command Options

```bash
python sync_schema_to_salesforce.py [OPTIONS]
```

**Options:**
- `--org_type {original,b2b,b2c}`: Which org type to sync (default: `original`)
- `--schema_file PATH`: Custom path to schema JSON (default: `schema_exports/{org_type}_schema.json`)
- `--dry-run`: Preview changes without applying them
- `--skip-existing`: Skip objects/fields that already exist (default: True)

**Examples:**

```bash
# Dry run for original org
python sync_schema_to_salesforce.py --org_type original --dry-run

# Sync B2B schema
python sync_schema_to_salesforce.py --org_type b2b

# Use custom schema file
python sync_schema_to_salesforce.py --schema_file my_custom_schema.json
```

## How It Works

### Field Type Inference

The script automatically infers Salesforce field types from field names and descriptions:

- **Lookup Fields**: Fields ending in `Id` or `Id__c` that reference other objects
- **Date/DateTime**: Fields with "date" or "timestamp" in description
- **Boolean**: Fields starting with "Is" or containing "boolean"
- **Email**: Fields with "email" in name
- **Phone**: Fields with "phone" in name
- **Number**: Fields with "number", "quantity", or "price" in description
- **Long Text**: Fields with "description" or "content" in description
- **Text**: Default for other fields

### Custom Objects

The script creates custom objects for:
- `Issue__c` - Custom object for issues
- `CaseHistory__c` - Custom object for case history

### Custom Fields on Standard Objects

The script adds custom fields to standard objects like:
- `Case.IssueId__c` - Lookup to Issue
- `Case.OrderItemId__c` - Lookup to OrderItem

## Limitations & Notes

### What Gets Created

✅ **Custom Objects**: Fully created with all fields
✅ **Custom Fields**: Created on both standard and custom objects
✅ **Field Types**: Automatically inferred and set

### What Doesn't Get Created

❌ **Standard Objects**: Already exist in Salesforce (Account, Contact, Case, etc.)
❌ **Standard Fields**: Already exist on standard objects
❌ **Record Types**: Not created (you may need to create these manually)
❌ **Validation Rules**: Not created
❌ **Workflows/Flows**: Not created
❌ **Data**: Only schema is synced, not actual data records

### Important Notes

1. **Field Type Inference**: The script tries to infer field types, but you may need to manually adjust some fields in Salesforce Setup if the inference is incorrect.

2. **Lookup Relationships**: Lookup fields are created, but you may need to verify the referenced object names match your org.

3. **Picklist Values**: If a field description mentions specific values (e.g., "One of ['value1', 'value2']"), the script will try to create a picklist with those values. Otherwise, picklists may need manual configuration.

4. **Permissions**: Make sure your Salesforce user has:
   - "Customize Application" permission
   - "Create Custom Objects" permission
   - "Modify All Data" permission (for Developer orgs, this is usually enabled by default)

5. **API Version**: The script uses API version `v58.0`. If you encounter issues, you may need to update this in the script.

## Troubleshooting

### Error: "INSUFFICIENT_ACCESS"

**Solution**: Your user needs "Customize Application" permission. In Salesforce:
- Setup → Users → Profiles → [Your Profile]
- Enable "Customize Application"

### Error: "DUPLICATE_VALUE" or "ALREADY_EXISTS"

**Solution**: The object/field already exists. The script should skip these automatically, but if you see this error, the object/field exists with different settings.

### Error: "INVALID_FIELD" or "INVALID_TYPE"

**Solution**: The field type inference may be incorrect. Check the field in the schema JSON and manually create it in Salesforce Setup with the correct type.

### Error: "CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY"

**Solution**: This usually means you're trying to modify a standard object/field that can't be changed, or there's a dependency issue. Check the error message for details.

### Field Type Issues

If a field is created with the wrong type:
1. Note which field has the issue
2. Delete it in Salesforce Setup
3. Manually create it with the correct type
4. Or modify the script's `infer_field_type()` function to handle your specific case

## Next Steps

After syncing the schema:

1. **Verify Schema**: Use `check_org_objects.py` to compare your org with the expected schema
2. **Load Data**: You'll need to load actual data records separately (see data loading guides)
3. **Test Queries**: Try running some CRMArena tasks to see if they work with your org

## Alternative: Manual Setup

If the automated sync doesn't work for your needs, you can manually create objects and fields in Salesforce Setup using the exported schema JSON as a reference. See `SALESFORCE_SCHEMA_SETUP.md` for manual setup instructions.

## Support

If you encounter issues:
1. Check the error messages - they usually indicate what's wrong
2. Try running with `--dry-run` first to preview changes
3. Verify your Salesforce user has the necessary permissions
4. Check that your schema JSON file is valid

