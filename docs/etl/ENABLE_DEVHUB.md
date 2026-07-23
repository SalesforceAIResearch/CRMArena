# How to Enable DevHub in Your Salesforce Org

The error "The specified org devhub is not a Dev Hub" means your org exists but DevHub features are not enabled.

## Enable DevHub in Salesforce UI

### Step 1: Log into Your Org

```bash
sf org open --target-org devhub
```

Or log in manually at: https://login.salesforce.com

### Step 2: Enable DevHub

1. **Go to Setup**:
   - Click the gear icon (⚙️) → **Setup**

2. **Enable DevHub**:
   - In Quick Find, search for: `Dev Hub`
   - Click on **Dev Hub** (under Developer Experience)
   - Check the box: **Enable Dev Hub**
   - Click **Save**

3. **Wait for Activation**:
   - This may take a few minutes
   - You'll see a confirmation when it's enabled

### Step 3: Verify DevHub is Enabled

```bash
# Check if DevHub is enabled
sf org list
```

The org should show with a 🌳 (tree) icon indicating it's a DevHub.

## Alternative: Use a Different Org as DevHub

If you can't enable DevHub in your current org, you can:

1. **Create a new Developer org** (if you don't have one):
   - Sign up at: https://developer.salesforce.com/signup
   - This will automatically have DevHub enabled

2. **Authenticate the new org**:
   ```bash
   sf org login web --alias devhub-new --set-default-dev-hub
   ```

3. **Update the config**:
   ```bash
   sf config set target-dev-hub=devhub-new --global
   ```

## Check DevHub Status

```bash
# List all orgs and see which is DevHub
sf org list

# Check config
sf config get target-dev-hub --json
```

## Troubleshooting

### "Dev Hub" Option Not Found in Setup
- Your org might not support DevHub
- Try creating a fresh Developer org
- Developer orgs should have DevHub available

### DevHub Takes Time to Enable
- Wait 5-10 minutes after enabling
- Log out and log back in
- Try creating a scratch org again

### Still Getting "Not a Dev Hub" Error
- Verify the org is actually enabled as DevHub
- Check that you're using the correct alias
- Try re-authenticating: `sf org login web --alias devhub --set-default-dev-hub`

