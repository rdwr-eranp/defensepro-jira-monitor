# GitHub Models API Setup Guide

## Issue Found

The current GitHub token doesn't have the required `models` permission to access GitHub Models API.

**Error:** `The 'models' permission is required to access this endpoint`

## Solution: Create New Token with Correct Permissions

### Option 1: GitHub Models API (Recommended)

1. **Go to GitHub Settings:**
   - Visit: https://github.com/settings/tokens
   - Click "Generate new token (classic)"

2. **Configure Token:**
   - **Name:** `DefensePro AI Insights`
   - **Expiration:** 90 days (or custom)
   - **Scopes Required:**
     - ✅ `repo` (if accessing private repos)
     - ✅ `read:org` (recommended)
     - ✅ `read:user`
   
3. **For GitHub Models Access:**
   - You may need to request access to GitHub Models preview
   - Visit: https://github.com/marketplace/models
   - Sign up for the preview program

4. **Update .env file:**
   ```
   GITHUB_TOKEN=your_new_token_here
   ```

### Option 2: Direct OpenAI API (Alternative)

If GitHub Models access requires waiting for preview approval, use OpenAI directly:

1. **Get OpenAI API Key:**
   - Visit: https://platform.openai.com/api-keys
   - Create new secret key

2. **Add to .env:**
   ```
   OPENAI_API_KEY=sk-your_openai_key_here
   ```

3. **Cost:** ~$0.01-0.02 per report with GPT-4o-mini

### Option 3: Azure OpenAI (Enterprise)

If your organization has Azure OpenAI:

1. **Get Azure credentials:**
   - Azure OpenAI endpoint
   - API key
   - Deployment name

2. **Add to .env:**
   ```
   AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
   AZURE_OPENAI_API_KEY=your_azure_key
   AZURE_OPENAI_DEPLOYMENT=gpt-4o
   ```

## Testing After Setup

Run the test script again:
```powershell
python test_ai_insights.py
```

## Integration Options

Once working, you can integrate AI insights into:
- `unified_weekly_report.py` - Weekly status reports
- `generate_gate_analysis.py` - Gate analysis
- `generate_release_readiness.py` - Release readiness

## Current Status

- ❌ GitHub Models API - Permission denied (needs models scope)
- ✅ OpenAI package installed
- ✅ Test script ready
- ⏳ Waiting for token with correct permissions

## Next Steps

1. Choose your preferred option above
2. Get the appropriate API key/token
3. Update .env file
4. Run `python test_ai_insights.py` to verify
5. Integrate into reports
