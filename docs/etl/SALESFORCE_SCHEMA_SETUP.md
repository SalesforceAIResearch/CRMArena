# Setting Up CRMArena Schema in Your Salesforce Org

The schema defines what Salesforce objects and fields are available for the CRMArena tasks. This guide explains how to understand and set up the schema in your own Salesforce org.

## Understanding the Schema

The schema is metadata that describes:
- **Objects**: Salesforce objects (like Account, Contact, Case, Opportunity, etc.)
- **Fields**: Fields within each object and their descriptions
- **Relationships**: How objects relate to each other

The schema is loaded from Hugging Face datasets and used by the agents to understand what queries they can make.

## Step 1: Export the Schema

First, export the schema to see what needs to be set up:

```bash
cd /Users/tarunanand/Benchmarks/CRMArena
source venv/bin/activate

# Export schema for original CRMArena
python export_schema.py --org_type original

# Or export all schemas
python export_schema.py --org_type all

# To see detailed information
python export_schema.py --org_type original --print_details
```

This will create:
- `schema_exports/original_schema.json` - Full schema with all objects and fields
- `schema_exports/original_schema_summary.json` - Summary of objects and field counts

## Step 2: Review the Schema

Open the exported JSON files to see:
1. **What objects are needed** (e.g., Account, Contact, Case, Opportunity, Lead, etc.)
2. **What fields each object has** and their descriptions
3. **How many fields** each object contains

Example structure:
```json
{
  "object": "Case",
  "fields": {
    "Id": "Unique identifier for the case",
    "Subject": "Subject line of the case",
    "Status": "Current status of the case",
    ...
  }
}
```

## Step 3: Setting Up Schema in Salesforce

**Important Note**: Setting up a complete schema in Salesforce is a complex task that typically requires:

1. **Standard Objects**: Most Salesforce orgs already have standard objects like:
   - Account, Contact, Lead, Opportunity, Case
   - User, Task, Event
   - Product, Pricebook, etc.

2. **Custom Objects**: You may need to create custom objects if the schema includes them

3. **Custom Fields**: You'll likely need to add custom fields to standard objects

4. **Field Types**: Ensure field types match (Text, Number, Date, Picklist, etc.)

5. **Relationships**: Set up lookup/master-detail relationships between objects

### Manual Setup (Recommended for Testing)

For a Developer org, you can manually set up objects and fields:

1. **Access Setup**:
   - Log into your Salesforce org
   - Click the gear icon → Setup

2. **Create Custom Objects** (if needed):
   - Go to: Object Manager → Create → Custom Object
   - Fill in the object details
   - Save

3. **Add Custom Fields**:
   - Go to: Object Manager → [Your Object] → Fields & Relationships
   - Click "New" to add fields
   - Match the field types from the schema

4. **Set Up Relationships**:
   - Create lookup or master-detail fields to link objects

### Using Salesforce Metadata API (Advanced)

For a more automated approach, you could:

1. **Export metadata** from the CRMArena test org (if you have access)
2. **Deploy metadata** to your org using:
   - Salesforce CLI (`sfdx`)
   - Workbench
   - VS Code with Salesforce Extensions

However, this requires access to the original test org's metadata.

## Step 4: Data Setup

Even with the correct schema, you'll also need **data** in your org. The tasks expect specific records to exist. This is even more complex than setting up the schema.

## Limitations and Alternatives

### Why Full Setup is Difficult

1. **Complexity**: CRMArena test orgs have been carefully configured with:
   - Many custom objects and fields
   - Specific data relationships
   - Pre-populated test data
   - Custom configurations

2. **Time Investment**: Setting up a complete replica would take significant time

3. **Metadata Access**: You'd need access to the original org's metadata

### Practical Alternatives

1. **Use the Test Org Credentials** (if they work):
   - This is the easiest option if the provided credentials are valid
   - Contact CRMArena maintainers if credentials expire

2. **Focus on Schema Understanding**:
   - Export and study the schema to understand what's needed
   - Use it as a reference for your own Salesforce development

3. **Partial Setup for Learning**:
   - Set up a subset of objects/fields for testing
   - Understand how the agents use the schema
   - Modify tasks to work with your simplified schema

4. **Contact Maintainers**:
   - Request access to a test org
   - Ask for metadata export files
   - Request setup documentation

## Step 5: Verify Your Schema

After setting up your schema, you can verify it matches:

```python
# Create a simple verification script
from crm_sandbox.env.connect_sandbox import SalesforceConnector

sf = SalesforceConnector(org_type="original")

# Try querying objects from the schema
objects_to_test = ["Account", "Contact", "Case", "Opportunity"]
for obj in objects_to_test:
    try:
        result = sf.run_query(f"SELECT Id FROM {obj} LIMIT 1")
        print(f" {obj}: Accessible")
    except Exception as e:
        print(f"❌ {obj}: {str(e)}")
```

## Schema Files Location

The schema is loaded from Hugging Face:
- **Original CRMArena**: `Salesforce/CRMArena` dataset, "schema" split
- **B2B**: `Salesforce/CRMArenaPro` dataset, "b2b_schema" split  
- **B2C**: `Salesforce/CRMArenaPro` dataset, "b2c_schema" split

You can also access these directly:
```python
from datasets import load_dataset

# Original schema
schema = load_dataset("Salesforce/CRMArena", "schema")
print(schema["test"])

# B2B schema
b2b_schema = load_dataset("Salesforce/CRMArenaPro", "b2b_schema")
print(b2b_schema["b2b_schema"])
```

## Summary

Setting up the complete CRMArena schema in a new Salesforce org is a significant undertaking. The schema export tool helps you understand what's needed, but full replication requires:

1. ✅ Exporting the schema (use `export_schema.py`)
2. ⚠️ Understanding the structure (review JSON files)
3. ⚠️ Setting up objects/fields in Salesforce (manual or via Metadata API)
4. ⚠️ Populating with test data (complex and time-consuming)

**Recommendation**: If possible, use the provided test org credentials. If those don't work, contact the CRMArena maintainers for assistance or metadata access.

