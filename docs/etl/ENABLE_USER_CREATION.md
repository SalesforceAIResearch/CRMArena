# Enabling User Creation via API in Salesforce

To create User records via the Salesforce API, you need to grant the **"Manage Users"** permission to your API user.

## Method 1: Using Permission Sets (Recommended)

This is the recommended approach as it's more flexible and follows best practices.

### Step 1: Create or Edit a Permission Set

1. **Navigate to Setup**:
   - Click the gear icon (⚙️) in the top right
   - Click **Setup**

2. **Find Permission Sets**:
   - In Quick Find, type: `Permission Sets`
   - Click **Permission Sets**

3. **Create or Edit Permission Set**:
   - If you don't have one for API access, click **New**
   - Name it: `API User Permissions` (or similar)
   - Click **Save**
   - If editing an existing one, click on it

### Step 2: Grant Manage Users Permission

1. **Go to System Permissions**:
   - In the Permission Set, click **System Permissions**
   - Click **Edit**

2. **Enable Required Permissions**:
   - Check the box for **Manage Users**
   - Check the box for **API Enabled** (if not already enabled)
   - Click **Save**

### Step 3: Assign Permission Set to Your API User

1. **Assign Permission Set**:
   - In the Permission Set, click **Manage Assignments**
   - Click **Add Assignments**
   - Select your API user (the one you use for API access)
   - Click **Assign**
   - Click **Done**

## Method 2: Using Profiles (Alternative)

If you prefer to modify the profile directly:

1. **Navigate to Setup** → **Profiles**
2. **Click on your API user's profile** (usually "System Administrator" for dev orgs)
3. **Click Edit**
4. **Under Administrative Permissions**, check:
   - ✅ **Manage Users**
   - ✅ **API Enabled** (if not already enabled)
5. **Click Save**

## Verify Permissions

After granting permissions, test by running:

```bash
python upload_data_to_salesforce.py --org_type original --only User --limit 1
```

If successful, you should see users being created. If you get permission errors, double-check:
- The permission set is assigned to your API user
- The API user is logged in with the credentials in your `.env` file
- You've saved and waited a few seconds for permissions to propagate

## Required Fields for User Creation

When creating User records via API, Salesforce requires:
- **Username** (must be unique, typically email format)
- **LastName**
- **Email**
- **Alias** (short name, max 8 characters)
- **ProfileId** or **Profile.Name** (must reference an existing Profile)
- **TimeZoneSidKey** (e.g., "America/New_York")
- **LocaleSidKey** (e.g., "en_US")
- **EmailEncodingKey** (e.g., "UTF-8")
- **LanguageLocaleKey** (e.g., "en_US")

The script will handle these requirements automatically.

## Troubleshooting

### Error: "INSUFFICIENT_ACCESS: Manage Users permission required"
- **Solution**: Follow Method 1 or 2 above to grant "Manage Users" permission

### Error: "DUPLICATE_USERNAME"
- **Solution**: The username already exists. The script will skip duplicate usernames.

### Error: "REQUIRED_FIELD_MISSING"
- **Solution**: The script should handle required fields automatically, but check that the User data includes all required fields.

## Notes

- **Developer Orgs**: In Developer Edition orgs, you typically have "System Administrator" profile which already has "Manage Users" permission, but you may still need to verify it's enabled.
- **License Limits**: Developer orgs have a limit on the number of users (usually 2-3). You can't create more users than your org's license limit.
- **Active Users**: New users are created as "Active" by default. To create inactive users, set `IsActive = false`.

