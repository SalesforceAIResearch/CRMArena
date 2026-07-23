# How to Enable Knowledge in Salesforce

This guide explains how to enable Salesforce Knowledge so you can sync the `Knowledge__kav` object and its fields from CRMArena.

## Step-by-Step Instructions

### Step 1: Enable Knowledge in Your Org

1. **Log into your Salesforce org**
   - Go to: https://login.salesforce.com/
   - Use your Developer org credentials

2. **Navigate to Setup**
   - Click the gear icon (⚙️) in the top right
   - Click **Setup**

3. **Enable Knowledge**
   - In the Quick Find box (top left), type: `Knowledge`
   - Click on **Knowledge Settings** (under Knowledge)

4. **Enable Knowledge**
   - Check the box: **Enable Knowledge**
   - Click **Save**

5. **Wait for Activation**
   - Salesforce will show a message that Knowledge is being enabled
   - This process can take a few minutes
   - You'll see a notification when it's complete

### Step 2: Configure Knowledge (Optional but Recommended)

After Knowledge is enabled, you may want to configure it:

1. **Set Up Knowledge Articles**
   - In Setup, search for "Knowledge Article Types"
   - Salesforce will create a default article type
   - You can customize this later if needed

2. **Set Up Data Categories** (Optional)
   - Search for "Data Category Groups" in Setup
   - Configure categories if you want to organize articles

### Step 3: Verify Knowledge is Enabled

1. **Check Object Manager**
   - Go to Setup → Object Manager
   - Search for "Knowledge"
   - You should see objects like:
     - `Knowledge__kav` (Knowledge Article Version)
     - `Knowledge__ka` (Knowledge Article)
     - `KnowledgeArticleVersion` (standard object)

2. **Test Query** (Optional)
   - You can test if Knowledge is accessible by running:
   ```bash
   python test_salesforce_connection.py original
   ```
   - Then try querying: `SELECT Id FROM Knowledge__kav LIMIT 1`

### Step 4: Re-run Schema Sync

Once Knowledge is enabled, re-run the sync script to create the Knowledge fields:

```bash
cd /Users/tarunanand/Benchmarks/CRMArena
source venv/bin/activate
python sync_schema_to_salesforce.py --org_type original
```

The script will now be able to create:
- `FAQ_Answer__c` field on `Knowledge__kav`

## Troubleshooting

### "Knowledge Settings" Not Found

If you don't see "Knowledge Settings" in Setup:
- Your org might not have Knowledge available
- Developer orgs should have it, but check your edition
- Try searching for "Knowledge" in Setup to find alternative paths

### Knowledge Takes Time to Enable

- The activation process can take 5-10 minutes
- Don't close the browser window
- Wait for the confirmation message

### Still Getting "Entity Not Found" Error

If you still get errors after enabling Knowledge:
1. Wait a few more minutes for full activation
2. Log out and log back into Salesforce
3. Verify the object exists in Object Manager
4. Check that your user has access to Knowledge objects

### Permission Issues

If you get permission errors:
- Make sure your user has "Customize Application" permission
- Check that Knowledge objects are accessible to your profile
- In Developer orgs, you should have full access by default

## Alternative: Skip Knowledge (If Not Needed)

If you don't need Knowledge for your CRMArena testing, you can:
1. Skip the Knowledge fields in the sync
2. The script will show a warning but continue with other objects
3. Your CRMArena tasks that don't require Knowledge will still work

## Next Steps

After enabling Knowledge and re-running the sync:
1. Verify the `FAQ_Answer__c` field was created
2. Check that it appears in Object Manager → Knowledge Article Version → Fields
3. You can now use Knowledge articles in your CRMArena tasks

