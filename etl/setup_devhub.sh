#!/bin/bash
# Helper script to set up DevHub for scratch org creation

echo "============================================================"
echo "Setting Up Salesforce DevHub"
echo "============================================================"
echo ""

# Check if Salesforce CLI is installed
if ! command -v sf &> /dev/null && ! command -v sfdx &> /dev/null; then
    echo "❌ Salesforce CLI not found!"
    echo ""
    echo "Please install Salesforce CLI first:"
    echo "  npm install -g @salesforce/cli"
    echo "  or"
    echo "  brew install salesforce-cli"
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

# Check if default dev hub is already set
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
    
    # If that didn't work, check org list for DevHub
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
    
    if [ -n "$DEFAULT_DEVHUB" ]; then
        echo "✅ Default DevHub already set: $DEFAULT_DEVHUB"
        echo ""
        echo "You can proceed to create scratch orgs."
        exit 0
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
    
    if [ -n "$DEFAULT_DEVHUB" ]; then
        echo "✅ Default DevHub already set: $DEFAULT_DEVHUB"
        echo ""
        echo "You can proceed to create scratch orgs."
        exit 0
    fi
fi

echo "⚠️  No default DevHub found"
echo ""

# Check if there are any authenticated orgs
if [ "$CLI_CMD" = "sf" ]; then
    ORG_LIST=$(sf org list --json 2>/dev/null || echo "[]")
    ORG_COUNT=$(echo "$ORG_LIST" | grep -c '"alias"' || echo "0")
else
    ORG_LIST=$(sfdx force:org:list --json 2>/dev/null || echo "[]")
    ORG_COUNT=$(echo "$ORG_LIST" | grep -c '"alias"' || echo "0")
fi

if [ "$ORG_COUNT" -gt 0 ]; then
    echo "Found authenticated orgs. You can set one as DevHub:"
    echo ""
    if [ "$CLI_CMD" = "sf" ]; then
        sf org list
        echo ""
        echo "To set an existing org as DevHub:"
        echo "  sf config set target-dev-hub=<alias> --global"
    else
        sfdx force:org:list
        echo ""
        echo "To set an existing org as DevHub:"
        echo "  sfdx force:config:set defaultdevhubusername=<alias>"
    fi
    echo ""
    read -p "Enter the alias of the org to use as DevHub (or press Enter to authenticate new): " DEVHUB_ALIAS
    
    if [ -n "$DEVHUB_ALIAS" ]; then
        if [ "$CLI_CMD" = "sf" ]; then
            sf config set target-dev-hub="$DEVHUB_ALIAS" --global
            echo "✅ Set $DEVHUB_ALIAS as default DevHub"
        else
            sfdx force:config:set defaultdevhubusername="$DEVHUB_ALIAS" --global
            echo "✅ Set $DEVHUB_ALIAS as default DevHub"
        fi
        exit 0
    fi
fi

echo "You need to authenticate with a DevHub org."
echo ""
echo "A DevHub org is a Salesforce org that can create scratch orgs."
echo "Any Developer Edition org can be used as a DevHub."
echo ""
echo "If you don't have a Developer org yet:"
echo "  1. Sign up at: https://developer.salesforce.com/signup"
echo "  2. Then come back and run this script again"
echo ""
read -p "Press Enter to authenticate with a DevHub org, or Ctrl+C to cancel..."

if [ "$CLI_CMD" = "sf" ]; then
    echo ""
    echo "Opening browser for authentication..."
    sf org login web --alias devhub --set-default-dev-hub
else
    echo ""
    echo "Opening browser for authentication..."
    sfdx auth:web:login --alias devhub --setdefaultdevhubusername
fi

echo ""
echo "✅ DevHub setup complete!"
echo ""
echo "You can now create scratch orgs using:"
echo "  ./create_scratch_org.sh"

