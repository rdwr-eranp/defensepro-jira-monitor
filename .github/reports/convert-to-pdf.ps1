# Read the markdown file
$mdContent = Get-Content "DefensePro-10.12.0.0-Release-Report.md" -Raw

# Convert markdown to HTML with proper styling
$html = @"
<!DOCTYPE html>
<html>
<head>
<meta charset='utf-8'>
<title>DefensePro 10.12.0.0 Release Report</title>
<style>
@media print {
    body { margin: 0.5in; }
}
body { 
    font-family: 'Segoe UI', 'Calibri', Arial, sans-serif; 
    line-height: 1.6; 
    max-width: 1000px; 
    margin: 0 auto; 
    padding: 20px; 
    color: #333; 
}
h1 { 
    color: #0066cc; 
    border-bottom: 3px solid #0066cc; 
    padding-bottom: 10px; 
    margin-top: 20px;
    font-size: 28px;
}
h2 { 
    color: #0066cc; 
    border-bottom: 2px solid #e0e0e0; 
    margin-top: 30px; 
    padding-bottom: 8px; 
    font-size: 22px;
}
h3 { 
    color: #333; 
    margin-top: 20px; 
    font-size: 18px;
}
h4 {
    color: #555;
    margin-top: 15px;
    font-size: 16px;
}
table { 
    border-collapse: collapse; 
    width: 100%; 
    margin: 20px 0; 
    font-size: 14px;
}
th, td { 
    border: 1px solid #ddd; 
    padding: 8px; 
    text-align: left; 
}
th { 
    background-color: #0066cc; 
    color: white; 
    font-weight: bold;
}
tr:nth-child(even) { 
    background-color: #f9f9f9; 
}
ul, ol { 
    margin-left: 30px; 
    margin-bottom: 10px;
}
li {
    margin-bottom: 5px;
}
strong { 
    color: #0066cc; 
    font-weight: 600;
}
em {
    color: #666;
}
code { 
    background-color: #f5f5f5; 
    padding: 2px 6px; 
    border-radius: 3px; 
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 13px;
}
hr {
    border: none;
    border-top: 1px solid #e0e0e0;
    margin: 30px 0;
}
.page-break {
    page-break-after: always;
}
</style>
</head>
<body>
"@

# Simple markdown to HTML conversion
$htmlBody = $mdContent
$htmlBody = $htmlBody -replace '# (.*)', '<h1>$1</h1>'
$htmlBody = $htmlBody -replace '## (.*)', '<h2>$1</h2>'
$htmlBody = $htmlBody -replace '### (.*)', '<h3>$1</h3>'
$htmlBody = $htmlBody -replace '#### (.*)', '<h4>$1</h4>'
$htmlBody = $htmlBody -replace '\*\*(.*?)\*\*', '<strong>$1</strong>'
$htmlBody = $htmlBody -replace '\*(.*?)\*', '<em>$1</em>'
$htmlBody = $htmlBody -replace '`(.*?)`', '<code>$1</code>'
$htmlBody = $htmlBody -replace '---', '<hr>'
$htmlBody = $htmlBody -replace '^- (.*)$', '<li>$1</li>' -split "`n" -join "`n"
$htmlBody = $htmlBody -replace '(\d+)\. (.*)$', '<li>$2</li>' -split "`n" -join "`n"
$htmlBody = $htmlBody -replace '(<li>.*</li>(?:\n<li>.*</li>)*)', '<ul>$1</ul>'
$htmlBody = $htmlBody -replace '\n\n', '</p><p>'
$htmlBody = '<p>' + $htmlBody + '</p>'
$htmlBody = $htmlBody -replace '<p></p>', ''

$html += $htmlBody
$html += @"
</body>
</html>
"@

# Save HTML file
$html | Out-File "DefensePro-10.12.0.0-Release-Report.html" -Encoding UTF8

Write-Host "HTML file created. Converting to PDF..." -ForegroundColor Green

# Convert to PDF using Edge
$edgeExe = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$htmlPath = (Get-Item "DefensePro-10.12.0.0-Release-Report.html").FullName
$pdfPath = $htmlPath -replace '\.html$', '.pdf'

if (Test-Path $edgeExe) {
    & $edgeExe --headless --disable-gpu --run-all-compositor-stages-before-draw --print-to-pdf-no-header --print-to-pdf=$pdfPath $htmlPath
    Start-Sleep -Seconds 5
    
    if (Test-Path $pdfPath) {
        $pdfSize = (Get-Item $pdfPath).Length
        Write-Host "PDF created successfully! Size: $pdfSize bytes" -ForegroundColor Green
        Write-Host "Location: $pdfPath" -ForegroundColor Cyan
    } else {
        Write-Host "PDF file not created. Check if Edge is working properly." -ForegroundColor Red
    }
} else {
    Write-Host "Microsoft Edge not found at: $edgeExe" -ForegroundColor Red
}
