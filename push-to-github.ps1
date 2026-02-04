#!/usr/bin/env pwsh
# Setup script to push to GitHub
# Usage: Edit the REPO_URL below with your GitHub repository URL

# Replace this with your GitHub repository URL
$REPO_URL = "https://github.com/rdwr-eranp/defensepro-jira-monitor.git"

Write-Host "`nPushing to GitHub..." -ForegroundColor Cyan
Write-Host "Repository: $REPO_URL`n" -ForegroundColor Yellow

# Add remote origin
git remote add origin $REPO_URL

# Set branch name to main (GitHub default)
git branch -M main

# Push to GitHub
git push -u origin main

Write-Host "`n✓ Repository pushed to GitHub successfully!" -ForegroundColor Green
Write-Host "View at: $($REPO_URL -replace '\.git$', '')" -ForegroundColor Cyan
