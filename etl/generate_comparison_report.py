#!/usr/bin/env python3
"""
Generate comprehensive comparison report between source database and Salesforce
"""

from simple_salesforce import Salesforce
import subprocess
import json
import sqlite3
from datetime import datetime

def main():
    # Connect to Salesforce
    result = subprocess.run(["sf", "org", "display", "--target-org", "crmarena-b2b", "--json"], 
                          capture_output=True, text=True)
    org_info = json.loads(result.stdout)["result"]
    sf = Salesforce(instance_url=org_info["instanceUrl"], session_id=org_info["accessToken"])

    # Connect to source database
    db = sqlite3.connect("local_data/crmarenapro_b2b_data.db")
    cursor = db.cursor()

    # Get list of all tables in source DB
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]

    print("=" * 100)
    print(f"B2B ETL COMPREHENSIVE COMPARISON REPORT")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 100)
    print()

    # Collect data for all objects
    results = []

    for table in tables:
        # Skip metadata tables
        if table in ["id_mappings", "sqlite_sequence"]:
            continue
        
        # Get count from source
        try:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            source_count = cursor.fetchone()[0]
        except:
            source_count = 0
        
        # Get count from Salesforce
        sf_count = 0
        sf_error = None
        try:
            sf_result = sf.query(f"SELECT COUNT() FROM {table}")
            sf_count = sf_result["totalSize"]
        except Exception as e:
            sf_error = str(e)[:50]
        
        results.append({
            "object": table,
            "source": source_count,
            "salesforce": sf_count,
            "error": sf_error
        })

    db.close()

    # Sort by source count (highest first)
    results.sort(key=lambda x: x["source"], reverse=True)

    # Categorize results
    successful = []
    partial = []
    failed = []
    not_applicable = []

    for r in results:
        if r["source"] == 0:
            not_applicable.append(r)
        elif r["salesforce"] == r["source"]:
            successful.append(r)
        elif r["salesforce"] > 0:
            partial.append(r)
        else:
            failed.append(r)

    # Print summary
    print("SUMMARY")
    print("-" * 100)
    print(f"Total Objects in Source Database: {len(results)}")
    print(f"Objects with Data: {len([r for r in results if r['source'] > 0])}")
    print(f"Successfully Uploaded (100%): {len(successful)}")
    print(f"Partially Uploaded: {len(partial)}")
    print(f"Failed/Not Uploaded: {len(failed)}")
    print(f"No Source Data: {len(not_applicable)}")
    print()

    # Detailed breakdown
    print("=" * 100)
    print("DETAILED BREAKDOWN")
    print("=" * 100)
    print()

    print("SUCCESS - FULLY UPLOADED (100%)")
    print("-" * 100)
    print(f"{'Object':<35} {'Source':<15} {'Salesforce':<15} {'Success Rate':<15}")
    print("-" * 100)
    total_source_success = 0
    total_sf_success = 0
    for r in successful:
        print(f"{r['object']:<35} {r['source']:<15,} {r['salesforce']:<15,} {'100%':<15}")
        total_source_success += r["source"]
        total_sf_success += r["salesforce"]
    print("-" * 100)
    print(f"{'TOTAL':<35} {total_source_success:<15,} {total_sf_success:<15,}")
    print()

    print("PARTIAL - SOME RECORDS MISSING")
    print("-" * 100)
    print(f"{'Object':<35} {'Source':<15} {'Salesforce':<15} {'Success Rate':<15} {'Missing':<15}")
    print("-" * 100)
    total_source_partial = 0
    total_sf_partial = 0
    total_missing = 0
    for r in partial:
        missing = r["source"] - r["salesforce"]
        success_rate = f"{r['salesforce']*100//r['source']}%" if r["source"] > 0 else "0%"
        print(f"{r['object']:<35} {r['source']:<15,} {r['salesforce']:<15,} {success_rate:<15} {missing:<15,}")
        total_source_partial += r["source"]
        total_sf_partial += r["salesforce"]
        total_missing += missing
    print("-" * 100)
    print(f"{'TOTAL':<35} {total_source_partial:<15,} {total_sf_partial:<15,} {'':<15} {total_missing:<15,}")
    print()

    print("FAILED - NOT UPLOADED (0%)")
    print("-" * 100)
    print(f"{'Object':<35} {'Source':<15} {'Reason':<50}")
    print("-" * 100)
    total_failed = 0
    for r in failed:
        reason = r["error"] if r["error"] else "Not uploaded"
        print(f"{r['object']:<35} {r['source']:<15,} {reason:<50}")
        total_failed += r["source"]
    print("-" * 100)
    print(f"{'TOTAL':<35} {total_failed:<15,}")
    print()

    # No data objects
    if not_applicable:
        print("NO SOURCE DATA")
        print("-" * 100)
        for r in not_applicable:
            print(f"{r['object']:<35}")
        print()

    # Overall statistics
    total_source = total_source_success + total_source_partial + total_failed
    total_uploaded = total_sf_success + total_sf_partial
    overall_success = (total_uploaded / total_source * 100) if total_source > 0 else 0

    print("=" * 100)
    print("OVERALL STATISTICS")
    print("=" * 100)
    print(f"Total Records in Source: {total_source:,}")
    print(f"Total Records Uploaded: {total_uploaded:,}")
    print(f"Total Records Missing: {total_source - total_uploaded:,}")
    print(f"Overall Success Rate: {overall_success:.2f}%")
    print()

    print("=" * 100)
    print("KNOWN LIMITATIONS & REASONS FOR FAILURES")
    print("=" * 100)
    print()
    print("Platform Limitations:")
    print("  - User: Scratch orgs have license limits (2-3 users max)")
    print("  - UserTerritory2Association: References Users that don't exist due to license limits")
    print()
    print("Data/Configuration Issues:")
    print("  - OrderItem: 3 records reference an activated Order (locked)")
    print()
    print("Objects Not in Upload Order:")
    print("  - Some objects may not have been included in the ETL process yet")
    print()
    print("=" * 100)

if __name__ == "__main__":
    main()

