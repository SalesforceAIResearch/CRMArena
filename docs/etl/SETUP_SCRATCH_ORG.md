# Setting Up a Salesforce Scratch Org

Scratch orgs are temporary Salesforce orgs with more storage and features than Developer orgs. They're perfect for testing and data uploads.

## Prerequisites

1. **Salesforce CLI** - Install if not already installed:
   ```bash
   # Install via npm (recommended)
   npm install -g @salesforce/cli
   
   # Or install via Homebrew (macOS)
   brew install salesforce-cli
   
   # Or download from: https://developer.salesforce.com/tools/salesforcecli
   ```

2. **Salesforce DevHub** - You need a DevHub org (free Developer org works):
   - Sign up at: https://developer.salesforce.com/signup
   - This will be your DevHub org

## Step 1: Install Salesforce CLI

Check if CLI is installed:
```bash
sf --version
# or
sfdx --version
```

If not installed, install it:
```bash
npm install -g @salesforce/cli
```

## Step 2: Authenticate with DevHub

**Important**: You need to authenticate with a DevHub org and set it as the default.

```bash
# Login to your DevHub org and set as default DevHub
sf org login web --alias devhub --set-default-dev-hub

# Or if using sfdx
sfdx auth:web:login --alias devhub --setdefaultdevhubusername
```

This will:
- Open a browser for you to log in to your DevHub org
- Set it as the default DevHub (required for creating scratch orgs)

**If you already have a DevHub authenticated but not set as default:**

```bash
# Set existing org as default DevHub
sf config set target-dev-hub=devhub

# Or if using sfdx
sfdx force:config:set defaultdevhubusername=devhub
```

**Verify DevHub is set:**

```bash
# Check default DevHub
sf config get target-dev-hub

# Or if using sfdx
sfdx force:config:get defaultdevhubusername
```

## Step 3: Create Scratch Org Definition File

Create a scratch org configuration file:

```bash
cd /Users/tarunanand/Benchmarks/CRMArena
mkdir -p config
```

Create `config/project-scratch-def.json`:

```json
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
```

## Step 4: Create Scratch Org

```bash
# Create a scratch org (valid for 7 days by default)
sf org create scratch --definition-file config/project-scratch-def.json --alias crmarena --duration-days 7 --set-default

# Or if using sfdx
sfdx force:org:create --definitionfile config/project-scratch-def.json --alias crmarena --durationdays 7 --setdefaultusername
```

This will:
- Create a new scratch org
- Set it as the default org
- Return org credentials

## Step 5: Get Scratch Org Credentials

```bash
# Get org info
sf org display --target-org crmarena

# Or if using sfdx
sfdx force:org:display --targetusername crmarena
```

This will show:
- Username
- Password (if set)
- Instance URL
- Access Token

## Step 6: Set Password for API Access

```bash
# Generate password
sf org generate password --target-org crmarena

# Or if using sfdx
sfdx force:user:password:generate --targetusername crmarena
```

## Step 7: Get Security Token

1. **Log into the scratch org**:
   ```bash
   sf org open --target-org crmarena
   ```

2. **Reset Security Token**:
   - Go to: Setup → My Personal Information → Reset My Security Token
   - Click "Reset Security Token"
   - Check your email for the token

## Step 8: Update .env File

Add scratch org credentials to your `.env` file:

```bash
# Scratch Org Credentials
SALESFORCE_SCRATCH_USERNAME=your-username@example.com
SALESFORCE_SCRATCH_PASSWORD=your-password
SALESFORCE_SCRATCH_SECURITY_TOKEN=your-security-token
```

## Step 9: Update Upload Script (Optional)

You can add scratch org support to the upload script, or use the existing `--org_type original` with scratch org credentials.

## Step 10: Upload Data

```bash
# Use scratch org credentials
python upload_data_to_salesforce.py --org_type original --skip User ProductCategory ProductCategoryProduct LiveChatTranscript
```

(Update your .env with scratch org credentials, or modify the script to support `--org_type scratch`)

## Scratch Org Benefits

✅ **More Storage**: 200MB data + 200MB files (vs 5MB in Developer org)  
✅ **More Features**: Enterprise edition features  
✅ **Clean Environment**: Fresh org each time  
✅ **No Limits**: No record count limits  
✅ **Easy Cleanup**: Just delete the org when done  

## Managing Scratch Org

### List Scratch Orgs
```bash
sf org list
```

### Open Scratch Org
```bash
sf org open --target-org crmarena
```

### Delete Scratch Org
```bash
sf org delete scratch --target-org crmarena
```

### Extend Scratch Org Duration
```bash
sf org extend --target-org crmarena --duration-days 30
```

## Quick Setup Script

I'll create a helper script to automate this process.

