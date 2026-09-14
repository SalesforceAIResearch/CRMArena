# Fixing "Storage Limit Exceeded" When Creating Scratch Org

If you get "STORAGE_LIMIT_EXCEEDED" when creating a scratch org, it means your **DevHub org** (not the scratch org) has hit its storage limit.

## The Problem

Scratch orgs are created FROM your DevHub org. If the DevHub org is full, you can't create scratch orgs.

## Solution 1: Clean Up DevHub Org (Recommended)

Clean up data in your DevHub org:

```bash
# Check what's using storage
python check_storage.py

# Clean up data (be careful - this deletes data!)
python cleanup_salesforce_data.py --org_type original --all-objects --confirm
```

**Important**: Make sure you're cleaning the **DevHub org**, not a scratch org. Check your `.env` file to see which org the scripts connect to.

## Solution 2: Use a Different DevHub

If your current DevHub is too full, use a fresh Developer org:

1. **Sign up for a new Developer org**:
   - https://developer.salesforce.com/signup
   - This will be clean with no data

2. **Authenticate it as DevHub**:
   ```bash
   sf org login web --alias devhub-clean --set-default-dev-hub
   sf config set target-dev-hub=devhub-clean --global
   ```

3. **Create scratch org**:
   ```bash
   ./create_scratch_org.sh
   ```

## Solution 3: Delete Old Scratch Orgs

Old scratch orgs might be taking up space:

```bash
# List all scratch orgs
sf org list scratch

# Delete old scratch orgs
sf org delete scratch --target-org <alias>
```

## Solution 4: Check DevHub Storage Directly

```bash
# Open DevHub org
sf org open --target-org devhub

# In the browser:
# Setup → Data Management → Storage Usage
# See what's using space and delete if needed
```

## Why This Happens

- **Developer orgs have limited storage**: 5MB data + 20MB files
- **DevHub needs space** to create scratch orgs
- **Old data accumulates** over time

## Prevention

- **Use scratch orgs for testing** (they have more storage: 200MB)
- **Clean up DevHub regularly**
- **Use a dedicated DevHub** that you keep clean
- **Delete scratch orgs when done**

## Quick Fix

The fastest solution is usually to use a fresh Developer org as DevHub:

```bash
# 1. Create new Developer org (sign up online)
# 2. Authenticate it
sf org login web --alias devhub-clean --set-default-dev-hub
sf config set target-dev-hub=devhub-clean --global

# 3. Create scratch org
./create_scratch_org.sh
```

