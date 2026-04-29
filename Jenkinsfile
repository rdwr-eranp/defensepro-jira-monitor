pipeline {
    // DefensePro Weekly Report Pipeline - v1.2
    agent { label 'built-in' }
    
    triggers {
        // Run every Wednesday at 9:00 AM
        cron('0 9 * * 3')
    }

    parameters {
        // --- Release ---
        string(
            name: 'VERSION',
            defaultValue: '10.14.0.0',
            description: 'Release version to report on (e.g. 10.14.0.0, 10.13.1.0). Overrides the hardcoded environment value.'
        )

        // --- Build range ---
        string(
            name: 'BUILDS',
            defaultValue: '',
            description: 'Comma-separated build numbers to include (e.g. 110,111,112). Leave empty for auto-detection from the database.'
        )

        // --- Sprint date range override ---
        string(
            name: 'SPRINT_START',
            defaultValue: '',
            description: 'Sprint start date override (YYYY-MM-DD). Leave empty to use the current active sprint.'
        )
        string(
            name: 'SPRINT_END',
            defaultValue: '',
            description: 'Sprint end date override (YYYY-MM-DD). Leave empty to use the current active sprint.'
        )

        // --- Report type ---
        choice(
            name: 'REPORT_TYPE',
            choices: ['unified', 'local', 'both'],
            description: 'Which report script to run: unified (Jenkins/email), local (local HTML), or both.'
        )

        // --- Email ---
        string(
            name: 'EMAIL_RECIPIENTS',
            defaultValue: 'eranp@radware.com',
            description: 'Comma-separated list of email recipients for the weekly report notification.'
        )
        booleanParam(
            name: 'SEND_QA_BUGS_EMAIL',
            defaultValue: false,
            description: 'Send a QA bugs notification email to all bug assignees (disabled by default).'
        )

        // --- Misc ---
        booleanParam(
            name: 'SKIP_AI_INSIGHTS',
            defaultValue: false,
            description: 'Skip AI-powered insights generation (faster run, useful for debugging).'
        )
    }
    
    stages {
        stage('Checkout') {
            steps {
                // Clone the repository
                git branch: 'main',
                    url: 'https://github.com/rdwr-eranp/defensepro-jira-monitor.git'
            }
        }

        stage('Resolve Parameters') {
            steps {
                script {
                    // VERSION: use parameter value (default keeps original 10.14.0.0)
                    env.VERSION = params.VERSION?.trim() ?: '10.14.0.0'

                    // BUILDS: pass through only if non-empty
                    env.BUILDS_OVERRIDE = params.BUILDS?.trim() ?: ''

                    // Sprint date range
                    env.SPRINT_START_OVERRIDE = params.SPRINT_START?.trim() ?: ''
                    env.SPRINT_END_OVERRIDE   = params.SPRINT_END?.trim()   ?: ''

                    // Misc flags
                    env.SKIP_AI_INSIGHTS_FLAG = params.SKIP_AI_INSIGHTS ? '1' : ''
                    env.REPORT_TYPE           = params.REPORT_TYPE ?: 'unified'
                    env.EMAIL_RECIPIENTS      = params.EMAIL_RECIPIENTS?.trim() ?: 'eranp@radware.com'

                    echo "=== Run Configuration ==="
                    echo "VERSION        : ${env.VERSION}"
                    echo "BUILDS         : ${env.BUILDS_OVERRIDE ?: '(auto-detect)'}"
                    echo "SPRINT_START   : ${env.SPRINT_START_OVERRIDE ?: '(current sprint)'}"
                    echo "SPRINT_END     : ${env.SPRINT_END_OVERRIDE   ?: '(current sprint)'}"
                    echo "REPORT_TYPE    : ${env.REPORT_TYPE}"
                    echo "EMAIL_RECIPIENTS: ${env.EMAIL_RECIPIENTS}"
                    echo "SKIP_AI_INSIGHTS: ${params.SKIP_AI_INSIGHTS}"
                    echo "SEND_QA_BUGS_EMAIL: ${params.SEND_QA_BUGS_EMAIL}"
                }
            }
        }

        stage('Load GitHub Token') {
            steps {
                script {
                    echo "[STAGE] Loading GitHub token credential..."
                    try {
                        withCredentials([string(credentialsId: 'dp_qa_copilot', variable: 'GH_TOKEN')]) {
                            env.GITHUB_TOKEN = GH_TOKEN
                            echo "✓ GitHub token loaded from Jenkins credential 'dp_qa_copilot' (length: ${env.GITHUB_TOKEN.length()})"
                        }
                    } catch (Exception e) {
                        echo "⚠ GitHub token not found in Jenkins credentials: ${e.message}"
                        echo "ℹ AI insights will be skipped unless GITHUB_TOKEN is in .env file"
                        env.GITHUB_TOKEN = ''
                    }
                }
            }
        }
        
        stage('Setup Python Environment') {
            steps {
                script {
                    if (isUnix()) {
                        sh '''
                            # Remove any stale HTML reports from the checkout so we only archive fresh ones
                            rm -f unified_weekly_report_*.html local_weekly_report_*.html qa_bugs_report.html open_bugs_report.html

                            # Create virtual environment if it doesn't exist
                            if [ ! -d "venv" ]; then
                                python3 -m venv venv
                            fi
                            
                            # Activate and install dependencies
                            . venv/bin/activate
                            pip install --upgrade pip
                            pip install -r requirements.txt
                        '''
                    } else {
                        bat '''
                            REM Remove any stale HTML reports from the checkout so we only archive fresh ones
                            del /Q unified_weekly_report_*.html 2>nul
                            del /Q local_weekly_report_*.html 2>nul
                            del /Q qa_bugs_report.html 2>nul
                            del /Q open_bugs_report.html 2>nul

                            REM Create virtual environment if it doesn't exist
                            if not exist venv (
                                python -m venv venv
                            )
                            
                            REM Activate and install dependencies
                            call venv\\Scripts\\activate.bat
                            python -m pip install --upgrade pip
                            pip install -r requirements.txt
                        '''
                    }
                }
            }
        }
        
        stage('Generate Unified Weekly Report') {
            when {
                expression { return env.REPORT_TYPE in ['unified', 'both'] }
            }
            steps {
                script {
                    echo "[STAGE] Generating unified weekly report for version ${env.VERSION}"
                    echo "GitHub token status: ${env.GITHUB_TOKEN ? 'Available (length: ' + env.GITHUB_TOKEN.length() + ')' : 'Not set - will check .env'}"

                    // Build optional env-var exports that only apply when the param is set
                    def extraUnix = ""
                    def extraBat  = ""
                    if (env.BUILDS_OVERRIDE) {
                        extraUnix += "export BUILDS='${env.BUILDS_OVERRIDE}'\n"
                        extraBat  += "set BUILDS=${env.BUILDS_OVERRIDE}\n"
                    }
                    if (env.SPRINT_START_OVERRIDE) {
                        extraUnix += "export SPRINT_START='${env.SPRINT_START_OVERRIDE}'\n"
                        extraBat  += "set SPRINT_START=${env.SPRINT_START_OVERRIDE}\n"
                    }
                    if (env.SPRINT_END_OVERRIDE) {
                        extraUnix += "export SPRINT_END='${env.SPRINT_END_OVERRIDE}'\n"
                        extraBat  += "set SPRINT_END=${env.SPRINT_END_OVERRIDE}\n"
                    }
                    if (env.SKIP_AI_INSIGHTS_FLAG) {
                        extraUnix += "export SKIP_AI_INSIGHTS=1\n"
                        extraBat  += "set SKIP_AI_INSIGHTS=1\n"
                    }

                    try {
                        withCredentials([
                            string(credentialsId: 'jira-url', variable: 'JIRA_URL'),
                            string(credentialsId: 'jira-email', variable: 'JIRA_EMAIL'),
                            string(credentialsId: 'jira-api-token', variable: 'JIRA_API_TOKEN'),
                            string(credentialsId: 'pg-password', variable: 'PG_PASSWORD')
                        ]) {
                            if (isUnix()) {
                                sh """
                                    . venv/bin/activate
                                    export VERSION=${env.VERSION}
                                    export GITHUB_TOKEN='${env.GITHUB_TOKEN}'
                                    ${extraUnix}
                                    python3 unified_weekly_report.py
                                """
                            } else {
                                bat """
                                    call venv\\Scripts\\activate.bat
                                    set VERSION=${env.VERSION}
                                    set GITHUB_TOKEN=${env.GITHUB_TOKEN}
                                    ${extraBat}
                                    python unified_weekly_report.py
                                """
                            }
                        }
                    } catch (Exception e) {
                        echo "Jenkins credentials not found, loading from .env file instead"
                        if (isUnix()) {
                            sh """
                                cd ${WORKSPACE}
                                . venv/bin/activate
                                export VERSION=${env.VERSION}
                                export GITHUB_TOKEN='${env.GITHUB_TOKEN}'
                                ${extraUnix}
                                if [ -f .env ]; then
                                    echo "Found .env file, loading environment variables..."
                                    set -a
                                    . ./.env
                                    set +a
                                else
                                    echo "ERROR: .env file not found!"
                                    exit 1
                                fi
                                python3 unified_weekly_report.py
                            """
                        } else {
                            bat """
                                cd %WORKSPACE%
                                call venv\\Scripts\\activate.bat
                                set VERSION=${env.VERSION}
                                set GITHUB_TOKEN=${env.GITHUB_TOKEN}
                                ${extraBat}
                                if exist .env (
                                    echo Found .env file, loading environment variables...
                                    for /f "usebackq tokens=* delims=" %%a in (".env") do set "%%a"
                                ) else (
                                    echo ERROR: .env file not found!
                                    exit /b 1
                                )
                                python unified_weekly_report.py
                            """
                        }
                    }
                }
            }
        }

        stage('Generate Local Weekly Report') {
            when {
                expression { return env.REPORT_TYPE in ['local', 'both'] }
            }
            steps {
                script {
                    echo "[STAGE] Generating local weekly report for version ${env.VERSION}"

                    def extraUnix = ""
                    def extraBat  = ""
                    if (env.BUILDS_OVERRIDE) {
                        extraUnix += "export BUILDS='${env.BUILDS_OVERRIDE}'\n"
                        extraBat  += "set BUILDS=${env.BUILDS_OVERRIDE}\n"
                    }
                    if (env.SPRINT_START_OVERRIDE) {
                        extraUnix += "export SPRINT_START='${env.SPRINT_START_OVERRIDE}'\n"
                        extraBat  += "set SPRINT_START=${env.SPRINT_START_OVERRIDE}\n"
                    }
                    if (env.SPRINT_END_OVERRIDE) {
                        extraUnix += "export SPRINT_END='${env.SPRINT_END_OVERRIDE}'\n"
                        extraBat  += "set SPRINT_END=${env.SPRINT_END_OVERRIDE}\n"
                    }
                    if (env.SKIP_AI_INSIGHTS_FLAG) {
                        extraUnix += "export SKIP_AI_INSIGHTS=1\n"
                        extraBat  += "set SKIP_AI_INSIGHTS=1\n"
                    }

                    try {
                        withCredentials([
                            string(credentialsId: 'jira-url', variable: 'JIRA_URL'),
                            string(credentialsId: 'jira-email', variable: 'JIRA_EMAIL'),
                            string(credentialsId: 'jira-api-token', variable: 'JIRA_API_TOKEN'),
                            string(credentialsId: 'pg-password', variable: 'PG_PASSWORD')
                        ]) {
                            if (isUnix()) {
                                sh """
                                    . venv/bin/activate
                                    export VERSION=${env.VERSION}
                                    export GITHUB_TOKEN='${env.GITHUB_TOKEN}'
                                    ${extraUnix}
                                    python3 local_weekly_report.py
                                """
                            } else {
                                bat """
                                    call venv\\Scripts\\activate.bat
                                    set VERSION=${env.VERSION}
                                    set GITHUB_TOKEN=${env.GITHUB_TOKEN}
                                    ${extraBat}
                                    python local_weekly_report.py
                                """
                            }
                        }
                    } catch (Exception e) {
                        echo "Jenkins credentials not found, loading from .env file instead"
                        if (isUnix()) {
                            sh """
                                cd ${WORKSPACE}
                                . venv/bin/activate
                                export VERSION=${env.VERSION}
                                export GITHUB_TOKEN='${env.GITHUB_TOKEN}'
                                ${extraUnix}
                                if [ -f .env ]; then
                                    set -a; . ./.env; set +a
                                else
                                    echo "ERROR: .env file not found!"; exit 1
                                fi
                                python3 local_weekly_report.py
                            """
                        } else {
                            bat """
                                cd %WORKSPACE%
                                call venv\\Scripts\\activate.bat
                                set VERSION=${env.VERSION}
                                set GITHUB_TOKEN=${env.GITHUB_TOKEN}
                                ${extraBat}
                                if exist .env (
                                    for /f "usebackq tokens=* delims=" %%a in (".env") do set "%%a"
                                ) else (
                                    echo ERROR: .env file not found! & exit /b 1
                                )
                                python local_weekly_report.py
                            """
                        }
                    }
                }
            }
        }
        
        stage('Archive Reports') {
            steps {
                // Archive only freshly generated HTML reports from this build
                archiveArtifacts artifacts: 'unified_weekly_report_*.html, local_weekly_report_*.html, qa_bugs_report.html, open_bugs_report.html',
                                 allowEmptyArchive: true,
                                 onlyIfSuccessful: false
            }
        }
        
        stage('Publish Reports') {
            steps {
                // Publish unified HTML report for viewing in Jenkins
                publishHTML([
                    allowMissing: false,
                    alwaysLinkToLastBuild: true,
                    keepAll: true,
                    reportDir: '.',
                    reportFiles: 'unified_weekly_report_*.html',
                    reportName: 'Unified Weekly Report',
                    reportTitles: 'DefensePro Unified Weekly Report'
                ])
            }
        }
        
        stage('QA Bugs Email') {
            when {
                expression { return params.SEND_QA_BUGS_EMAIL == true }
            }
            steps {
                script {
                    echo "[STAGE] Generating QA bugs email..."
                    try {
                        withCredentials([
                            string(credentialsId: 'jira-url',       variable: 'JIRA_URL'),
                            string(credentialsId: 'jira-email',     variable: 'JIRA_EMAIL'),
                            string(credentialsId: 'jira-api-token', variable: 'JIRA_API_TOKEN')
                        ]) {
                            if (isUnix()) {
                                sh """
                                    . venv/bin/activate
                                    export JIRA_URL=${JIRA_URL}
                                    export JIRA_EMAIL=${JIRA_EMAIL}
                                    export JIRA_API_TOKEN=${JIRA_API_TOKEN}
                                    python3 send_qa_bugs_notification.py --output-html qa_bugs_report.html
                                """
                            } else {
                                bat """
                                    call venv\\Scripts\\activate.bat
                                    set JIRA_URL=${JIRA_URL}
                                    set JIRA_EMAIL=${JIRA_EMAIL}
                                    set JIRA_API_TOKEN=${JIRA_API_TOKEN}
                                    python send_qa_bugs_notification.py --output-html qa_bugs_report.html
                                """
                            }
                        }
                    } catch (Exception e) {
                        echo "Jenkins credentials not found, loading from .env file"
                        if (isUnix()) {
                            sh """
                                . venv/bin/activate
                                set -a; . ./.env; set +a
                                python3 send_qa_bugs_notification.py --output-html qa_bugs_report.html
                            """
                        } else {
                            bat """
                                call venv\\Scripts\\activate.bat
                                for /f "usebackq tokens=* delims=" %%a in (".env") do set "%%a"
                                python send_qa_bugs_notification.py --output-html qa_bugs_report.html
                            """
                        }
                    }

                    // Read recipients and HTML written by Python
                    def recipients = readFile('qa_bugs_report.html.recipients.txt').trim()
                    def htmlBody   = readFile('qa_bugs_report.html')

                    if (recipients) {
                        emailext(
                            subject: "Action Required: Bugs on QA \u2013 DefensePro ${VERSION}",
                            body: htmlBody,
                            mimeType: 'text/html',
                            to: recipients
                        )
                        echo "✓ QA bugs email sent to: ${recipients}"
                    } else {
                        echo "ℹ No bug assignees found – email skipped."
                    }
                }
            }
        }

        stage('Email Notification') {
            steps {
                script {
                    def reportDate = new Date().format('MMMM dd, yyyy')
                    
                    mail(
                        subject: "DefensePro ${env.VERSION} - Unified Weekly Report (${reportDate})",
                        body: """<h2>DefensePro Unified Weekly Status Report</h2>
                        <p><strong>Release Version:</strong> ${env.VERSION}</p>
                        <p><strong>Report Date:</strong> ${reportDate}</p>
                        <p><strong>Build:</strong> #${BUILD_NUMBER}</p>
                        
                        <h3>Report Contents:</h3>
                        <ul>
                            <li>Bug Status (Dev, QA, Closed)</li>
                            <li>CI Iteration Automation Status</li>
                            <li>Platform Type & Mode Coverage</li>
                            <li>Critical Test Failures</li>
                            <li>Sub Test Execution Progress</li>
                        </ul>
                        
                        <p><a href="http://10.185.10.200:8080/job/DefensePro-Weekly-Report/${BUILD_NUMBER}/Unified_20Weekly_20Report/" style="padding: 10px 20px; background-color: #1976d2; color: white; text-decoration: none; border-radius: 4px; display: inline-block;">View Unified Report</a></p>
                        
                        <p><a href="${BUILD_URL}artifact/">Download Artifacts (HTML)</a></p>
                        
                        <p>View full details in Jenkins: <a href="${BUILD_URL}">${BUILD_URL}</a></p>
                        
                        <hr>
                        <p><em>Automated report generated by Jenkins</em></p>
                        """,
                        mimeType: 'text/html',
                        to: env.EMAIL_RECIPIENTS
                    )
                }
            }
        }
    }
    
    post {
        success {
            echo '✓ Weekly report generated successfully!'
        }
        failure {
            mail(
                subject: "FAILED: DefensePro Weekly Report - ${env.VERSION}",
                body: """
                <h2>Weekly Report Generation Failed</h2>
                <p><strong>Build:</strong> #${BUILD_NUMBER}</p>
                <p><strong>Status:</strong> FAILED</p>
                
                <p>Check the console output: <a href="${BUILD_URL}console">${BUILD_URL}console</a></p>
                """,
                mimeType: 'text/html',
                to: env.EMAIL_RECIPIENTS
            )
        }
    }
}
