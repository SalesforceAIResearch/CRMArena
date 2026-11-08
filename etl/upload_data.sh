#!/bin/bash
# Script to upload CRMArena data to Salesforce
# This script uploads all objects in the correct dependency order

cd "$(dirname "$0")"
source venv/bin/activate

echo "============================================================"
echo "Uploading CRMArena Data to Salesforce"
echo "============================================================"
echo ""
echo "This will upload data for all objects except:"
echo "  - User (requires 'Manage Users' permission - can be enabled)"
echo "  - ProductCategory (requires B2B Commerce - not available in Developer org)"
echo "  - ProductCategoryProduct (depends on ProductCategory)"
echo "  - LiveChatTranscript (requires Live Agent - auto-skipped if not enabled)"
echo ""
echo "Press Ctrl+C to cancel, or wait 5 seconds to continue..."
sleep 5

# Upload all objects, skipping those that require special setup
python upload_data_to_salesforce.py \
    --org_type original \
    --skip User ProductCategory ProductCategoryProduct LiveChatTranscript

echo ""
echo "============================================================"
echo "Upload Complete!"
echo "============================================================"
echo ""
echo "To upload specific objects, use:"
echo "  python upload_data_to_salesforce.py --org_type original --only <ObjectName>"
echo ""
echo "To upload with a limit:"
echo "  python upload_data_to_salesforce.py --org_type original --limit 10"
echo ""

