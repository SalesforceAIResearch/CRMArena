# Simple Scratch Org Setup Guide

## Quick Setup (3 Steps)

### Step 1: Install Salesforce CLI

```bash
npm install -g @salesforce/cli
```

### Step 2: Authenticate with DevHub

```bash
# This will open a browser - log in with your Developer org
sf org login web --alias devhub --set-default-dev-hub
```

**Note**: If you don't have a Developer org, sign up at: https://developer.salesforce.com/signup

### Step 3: Create Scratch Org

```bash
cd /Users/tarunanand/Benchmarks/CRMArena
./create_scratch_org.sh
```

## Manual Alternative

If the script doesn't work, create manually:

```bash
# 1. Authenticate
sf org login web --alias devhub --set-default-dev-hub

# 2. Create scratch org
sf org create scratch \
    --definition-file config/project-scratch-def.json \
    --alias crmarena \
    --duration-days 7 \
    --set-default

# 3. Generate password
sf org generate password --target-org crmarena

# 4. Get org info
sf org display --target-org crmarena
```

## Get Security Token

1. Open org: `sf org open --target-org crmarena`
2. Go to: Setup → My Personal Information → Reset My Security Token
3. Check email for token

## Update .env

```bash
SALESFORCE_USERNAME=<username-from-org-display>
SALESFORCE_PASSWORD=<password-from-generate-password>
SALESFORCE_SECURITY_TOKEN=<token-from-email>
```

## Upload Data

```bash
python upload_data_to_salesforce.py --org_type original --skip User ProductCategory ProductCategoryProduct LiveChatTranscript
```

## Troubleshooting

### "No default dev hub found"
- Run: `sf org login web --alias devhub --set-default-dev-hub`
- Verify: `sf config get target-dev-hub --json`

### "No authorization information found"
- The DevHub alias doesn't exist
- Re-authenticate: `sf org login web --alias devhub --set-default-dev-hub`

### Script parsing errors
- Use manual commands above instead
- The scripts are helpers, but manual commands always work

