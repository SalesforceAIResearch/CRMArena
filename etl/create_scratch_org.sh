#!/bin/bash
# Script to create a Salesforce scratch org for CRMArena data upload

set -e

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Parent directory (CRMArena root)
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "============================================================"
echo "Creating Salesforce Scratch Org for CRMArena"
echo "============================================================"
echo ""

# Check if Salesforce CLI is installed
if ! command -v sf &> /dev/null && ! command -v sfdx &> /dev/null; then
    echo "❌ Salesforce CLI not found!"
    echo ""
    echo "Please install Salesforce CLI:"
    echo "  npm install -g @salesforce/cli"
    echo "  or"
    echo "  brew install salesforce-cli"
    echo ""
    echo "See SETUP_SCRATCH_ORG.md for details"
    exit 1
fi

# Use sf if available, otherwise sfdx
if command -v sf &> /dev/null; then
    CLI_CMD="sf"
else
    CLI_CMD="sfdx"
fi

echo "✅ Using Salesforce CLI: $CLI_CMD"
echo ""

# Check if default dev hub is set
echo "Checking DevHub setup..."
if [ "$CLI_CMD" = "sf" ]; then
    # Get DevHub from JSON output using Python (macOS-compatible)
    CONFIG_JSON=$(sf config get target-dev-hub --json 2>/dev/null || echo "{}")
    DEFAULT_DEVHUB=$(echo "$CONFIG_JSON" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    result = data.get('result', [])
    if isinstance(result, list) and len(result) > 0:
        value = result[0].get('value', '')
        if value:
            print(value)
except:
    pass
" 2>/dev/null || echo "")
    
    # If still empty, check org list for DevHub
    if [ -z "$DEFAULT_DEVHUB" ]; then
        ORG_LIST=$(sf org list --json 2>/dev/null || echo "{}")
        DEFAULT_DEVHUB=$(echo "$ORG_LIST" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    result = data.get('result', {})
    non_scratch = result.get('nonScratchOrgs', [])
    for org in non_scratch:
        if org.get('isDefaultDevHub'):
            print(org.get('alias', ''))
            break
except:
    pass
" 2>/dev/null || echo "")
    fi
    
    if [ -z "$DEFAULT_DEVHUB" ]; then
        echo "⚠️  No default DevHub found"
        echo ""
        echo "Please set up DevHub first by running:"
        echo "  ./setup_devhub.sh"
        echo ""
        echo "Or manually:"
        echo "  sf org login web --alias devhub --set-default-dev-hub"
        echo ""
        exit 1
    else
        echo "✅ Default DevHub: $DEFAULT_DEVHUB"
        
        # Verify the DevHub is actually enabled by checking org list
        # The tree icon (🌳) in CLI output indicates DevHub
        ORG_LIST_TEXT=$(sf org list 2>/dev/null || echo "")
        if echo "$ORG_LIST_TEXT" | grep -q "🌳.*$DEFAULT_DEVHUB"; then
            echo "✅ Verified: DevHub is enabled (🌳 icon found)"
        else
            echo "⚠️  Warning: Could not verify DevHub status"
            echo "   If you see 'Not a Dev Hub' error, enable it:"
            echo "   1. Open org: sf org open --target-org $DEFAULT_DEVHUB"
            echo "   2. Go to: Setup → Dev Hub → Enable Dev Hub"
            echo "   See ENABLE_DEVHUB.md for details"
        fi
    fi
else
    DEFAULT_DEVHUB=$(sfdx force:config:get defaultdevhubusername --json 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    result = data.get('result', [])
    if isinstance(result, list) and len(result) > 0:
        value = result[0].get('value', '')
        if value:
            print(value)
except:
    pass
" 2>/dev/null || echo "")
    
    if [ -z "$DEFAULT_DEVHUB" ]; then
        echo "⚠️  No default DevHub found"
        echo ""
        echo "Please set up DevHub first by running:"
        echo "  ./setup_devhub.sh"
        echo ""
        echo "Or manually:"
        echo "  sfdx auth:web:login --alias devhub --setdefaultdevhubusername"
        echo ""
        exit 1
    else
        echo "✅ Default DevHub: $DEFAULT_DEVHUB"
    fi
fi

# Create config directory in project root if it doesn't exist
mkdir -p "$PROJECT_ROOT/config"

# Check if scratch org definition exists
if [ ! -f "$PROJECT_ROOT/config/project-scratch-def.json" ]; then
    echo "Creating scratch org definition file..."
    cat > "$PROJECT_ROOT/config/project-scratch-def.json" << 'EOF'
{
  "orgName": "CRMArena Test Org",
  "edition": "Enterprise",
  "features": ["EnableSetPasswordInApi"],
  "settings": {
    "lightningExperienceSettings": {
      "enableS1DesktopEnabled": true
    },
    "mobileSettings": {
      "enableS1EncryptedStoragePref2": false
    },
    "securitySettings": {
      "passwordPolicies": {
        "enableSetPasswordInApi": true
      }
    }
  }
}
EOF
    echo "✅ Created config/project-scratch-def.json"
fi

# Create scratch org
SCRATCH_ALIAS="crmarena-$(date +%s)"
echo ""
echo "Creating scratch org (alias: $SCRATCH_ALIAS)..."
echo "This may take a few minutes..."

if [ "$CLI_CMD" = "sf" ]; then
    # Create scratch org - if DevHub is set, it will be used automatically
    # Don't pass --target-dev-hub if it's already the default
    CREATE_OUTPUT=$(sf org create scratch \
        --definition-file "$PROJECT_ROOT/config/project-scratch-def.json" \
        --alias "$SCRATCH_ALIAS" \
        --duration-days 7 \
        --set-default 2>&1)
    CREATE_EXIT_CODE=$?
    
    if [ $CREATE_EXIT_CODE -ne 0 ]; then
        echo ""
        if echo "$CREATE_OUTPUT" | grep -q "STORAGE_LIMIT_EXCEEDED"; then
            echo "❌ Error: DevHub org storage limit exceeded"
            echo ""
            echo "Your DevHub org has hit its storage limit and cannot create scratch orgs."
            echo ""
            echo "Solutions:"
            echo "  1. Clean up DevHub org: python cleanup_salesforce_data.py --org_type original --all-objects --confirm"
            echo "  2. Use a fresh Developer org as DevHub (see FIX_SCRATCH_ORG_STORAGE.md)"
            echo "  3. Delete old scratch orgs: sf org list scratch"
            echo ""
            echo "See FIX_SCRATCH_ORG_STORAGE.md for detailed instructions"
            exit 1
        else
            echo "$CREATE_OUTPUT"
            exit 1
        fi
    fi
else
    sfdx force:org:create \
        --definitionfile "$PROJECT_ROOT/config/project-scratch-def.json" \
        --alias "$SCRATCH_ALIAS" \
        --durationdays 7 \
        --setdefaultusername
fi

echo ""
echo "✅ Scratch org created!"
echo ""

# Generate password
echo "Generating password..."
if [ "$CLI_CMD" = "sf" ]; then
    PASSWORD_OUTPUT=$(sf org generate password --target-org "$SCRATCH_ALIAS")
    PASSWORD=$(echo "$PASSWORD_OUTPUT" | python3 -c "
import sys
for line in sys.stdin:
    if 'Password:' in line:
        parts = line.split('Password:')
        if len(parts) > 1:
            print(parts[1].strip().split()[0])
            break
" 2>/dev/null || echo "")
else
    PASSWORD_OUTPUT=$(sfdx force:user:password:generate --targetusername "$SCRATCH_ALIAS")
    PASSWORD=$(echo "$PASSWORD_OUTPUT" | python3 -c "
import sys
for line in sys.stdin:
    if 'Password:' in line:
        parts = line.split('Password:')
        if len(parts) > 1:
            print(parts[1].strip().split()[0])
            break
" 2>/dev/null || echo "")
fi

# Get org info
echo "Getting org information..."
if [ "$CLI_CMD" = "sf" ]; then
    ORG_INFO=$(sf org display --target-org "$SCRATCH_ALIAS" --json)
    USERNAME=$(echo "$ORG_INFO" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    result = data.get('result', {})
    print(result.get('username', ''))
except:
    pass
" 2>/dev/null || echo "")
    INSTANCE_URL=$(echo "$ORG_INFO" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    result = data.get('result', {})
    print(result.get('instanceUrl', ''))
except:
    pass
" 2>/dev/null || echo "")
else
    ORG_INFO=$(sfdx force:org:display --targetusername "$SCRATCH_ALIAS" --json)
    USERNAME=$(echo "$ORG_INFO" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    result = data.get('result', {})
    print(result.get('username', ''))
except:
    pass
" 2>/dev/null || echo "")
    INSTANCE_URL=$(echo "$ORG_INFO" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    result = data.get('result', {})
    print(result.get('instanceUrl', ''))
except:
    pass
" 2>/dev/null || echo "")
fi

echo ""
echo "============================================================"
echo "Scratch Org Created Successfully!"
echo "============================================================"
echo ""
echo "Org Alias: $SCRATCH_ALIAS"
echo "Username: $USERNAME"
if [ -n "$PASSWORD" ]; then
    echo "Password: $PASSWORD"
fi
echo "Instance URL: $INSTANCE_URL"
echo ""
echo "============================================================"
echo "Next Steps:"
echo "============================================================"
echo ""
echo "1. Get Security Token:"
echo "   - Open org: $CLI_CMD org open --target-org $SCRATCH_ALIAS"
echo "   - Go to: Setup → My Personal Information → Reset My Security Token"
echo "   - Check email for security token"
echo ""
echo "2. Update .env file with scratch org credentials:"
echo "   SALESFORCE_USERNAME=$USERNAME"
if [ -n "$PASSWORD" ]; then
    echo "   SALESFORCE_PASSWORD=$PASSWORD"
fi
echo "   SALESFORCE_SECURITY_TOKEN=<from email>"
echo ""
echo "3. Upload data (from etl folder):"
echo "   python upload_data_to_salesforce.py --org_type original --skip User ProductCategory ProductCategoryProduct LiveChatTranscript"
echo ""
echo "4. When done, delete scratch org:"
if [ "$CLI_CMD" = "sf" ]; then
    echo "   sf org delete scratch --target-org $SCRATCH_ALIAS"
else
    echo "   sfdx force:org:delete --targetusername $SCRATCH_ALIAS"
fi
echo ""

