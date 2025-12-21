#!/usr/bin/env python3
"""
Export schema from Hugging Face datasets to JSON files.
This helps you understand what objects and fields need to be set up in your Salesforce org.
"""

import json
import argparse
from datasets import load_dataset
from crm_sandbox.data.assets import SCHEMA_ORIGINAL, B2B_SCHEMA, B2C_SCHEMA

def export_schema(schema_obj, output_file, org_type):
    """Export schema to a JSON file."""
    print(f"\n{'='*60}")
    print(f"Exporting {org_type} schema to {output_file}")
    print(f"{'='*60}\n")
    
    # Create a summary
    summary = {
        "org_type": org_type,
        "total_objects": len(schema_obj),
        "objects": []
    }
    
    for item in schema_obj:
        obj_info = {
            "object": item.get("object", "Unknown"),
            "field_count": len(item.get("fields", {})),
            "fields": item.get("fields", {})
        }
        summary["objects"].append(obj_info)
        print(f"  ✓ {obj_info['object']}: {obj_info['field_count']} fields")
    
    # Save full schema
    with open(output_file, 'w') as f:
        json.dump(schema_obj, f, indent=2)
    
    # Save summary
    summary_file = output_file.replace('.json', '_summary.json')
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\nFull schema saved to: {output_file}")
    print(f"Summary saved to: {summary_file}")
    print(f"\nTotal objects: {len(schema_obj)}")
    
    return summary

def print_schema_details(schema_obj, org_type):
    """Print detailed information about the schema."""
    print(f"\n{'='*60}")
    print(f"Schema Details for {org_type}")
    print(f"{'='*60}\n")
    
    for item in schema_obj:
        obj_name = item.get("object", "Unknown")
        fields = item.get("fields", {})
        
        print(f"\n📋 Object: {obj_name}")
        print(f"   Fields ({len(fields)}):")
        for field_name, field_desc in list(fields.items())[:10]:  # Show first 10
            desc = field_desc[:60] + "..." if len(field_desc) > 60 else field_desc
            print(f"     - {field_name}: {desc}")
        if len(fields) > 10:
            print(f"     ... and {len(fields) - 10} more fields")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export schema from Hugging Face datasets")
    parser.add_argument(
        "--org_type",
        type=str,
        default="original",
        choices=["original", "b2b", "b2c", "all"],
        help="Organization type to export schema for"
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="../schema_exports",
        help="Directory to save exported schema files"
    )
    parser.add_argument(
        "--print_details",
        action="store_true",
        help="Print detailed schema information to console"
    )
    args = parser.parse_args()
    
    import os
    os.makedirs(args.output_dir, exist_ok=True)
    
    schemas_to_export = []
    if args.org_type == "all":
        schemas_to_export = [
            ("original", SCHEMA_ORIGINAL),
            ("b2b", B2B_SCHEMA),
            ("b2c", B2C_SCHEMA)
        ]
    elif args.org_type == "original":
        schemas_to_export = [("original", SCHEMA_ORIGINAL)]
    elif args.org_type == "b2b":
        schemas_to_export = [("b2b", B2B_SCHEMA)]
    elif args.org_type == "b2c":
        schemas_to_export = [("b2c", B2C_SCHEMA)]
    
    for org_type, schema_obj in schemas_to_export:
        output_file = os.path.join(args.output_dir, f"{org_type}_schema.json")
        summary = export_schema(schema_obj, output_file, org_type)
        
        if args.print_details:
            print_schema_details(schema_obj, org_type)
    
    print(f"\n{'='*60}")
    print("Schema Export Complete!")
    print(f"{'='*60}")
    print("\nNext steps:")
    print("1. Review the exported JSON files to see what objects/fields are needed")
    print("2. See SALESFORCE_SCHEMA_SETUP.md for instructions on setting up the schema")
    print(f"{'='*60}\n")

