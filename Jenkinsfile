pipeline {
    // DefensePro Weekly Report Pipeline - v1.0
    agent { label 'built-in' }
    
    triggers {
        // Run every Wednesday at 9:00 AM
        cron('0 9 * * 3')
    }
    
    environment {
        // Release version to track
        VERSION = '10.13.0.0'
        // Build range for CI iteration status (comma-separated)
        BUILDS = '100,101,102,103,104,105,106'
    }
    
    stages {
        stage('Checkout') {
            steps {
                // Clone the repository
                git branch: 'main',
                    url: 'https://github.com/rdwr-eranp/defensepro-jira-monitor.git'
            }
        }
        
        stage('Setup Python Environment') {
            steps {
                script {
                    if (isUnix()) {
                        sh '''
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
            steps {
                script {
                    def timestamp = new Date().format('yyyy-MM-dd_HHmm')
                    echo "Generating unified weekly report for version ${VERSION}"
                    
                    // Credentials can be provided either via:
                    // 1. Jenkins credentials (jira-url, jira-email, jira-api-token, pg-password)
                    // 2. .env file in the workspace
                    
                    // Try to use Jenkins credentials if available, otherwise fall back to .env
                    def hasCredentials = true
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
                                    export VERSION=${VERSION}
                                    export BUILDS=${BUILDS}
                                    python3 unified_weekly_report.py
                                """
                            } else {
                                bat """
                                    call venv\\Scripts\\activate.bat
                                    set VERSION=${VERSION}
                                    set BUILDS=${BUILDS}
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
                                export VERSION=${VERSION}
                                export BUILDS=${BUILDS}
                                
                                # Load environment variables from .env file
                                if [ -f .env ]; then
                                    echo "Found .env file, loading environment variables..."
                                    set -a  # automatically export all variables
                                    . ./.env
                                    set +a
                                else
                                    echo "ERROR: .env file not found! Please create .env file with credentials."
                                    echo "Required variables: JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, PG_PASSWORD"
                                    exit 1
                                fi
                                
                                python3 unified_weekly_report.py
                            """
                        } else {
                            bat """
                                cd %WORKSPACE%
                                call venv\\Scripts\\activate.bat
                                set VERSION=${VERSION}
                                set BUILDS=${BUILDS}
                                
                                REM Load environment variables from .env file
                                if exist .env (
                                    echo Found .env file, loading environment variables...
                                    for /f "usebackq tokens=* delims=" %%a in (".env") do (
                                        set "%%a"
                                    )
                                ) else (
                                    echo ERROR: .env file not found! Please create .env file with credentials.
                                    echo Required variables: JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, PG_PASSWORD
                                    exit /b 1
                                )
                                
                                python unified_weekly_report.py
                            """
                        }
                    }
                }
            }
        }
        
        stage('Archive Reports') {
            steps {
                // Archive unified weekly report as Jenkins artifact
                archiveArtifacts artifacts: 'unified_weekly_report_*.html, open_bugs_report.html', 
                                 allowEmptyArchive: true,
                                 fingerprint: true,
                                 onlyIfSuccessful: true
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
        
        stage('Email Notification') {
            steps {
                script {
                    def reportDate = new Date().format('MMMM dd, yyyy')
                    
                    emailext(
                        subject: "DefensePro ${VERSION} - Unified Weekly Report (${reportDate})",
                        body: """<h2>DefensePro Unified Weekly Status Report</h2>
                        <p><strong>Release Version:</strong> ${VERSION}</p>
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
                        to: 'eranp@radware.com',
                        attachmentsPattern: '**/unified_weekly_report_*.html',
                        attachLog: false
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
            emailext(
                subject: "FAILED: DefensePro Weekly Report - ${env.VERSION}",
                body: """
                <h2>Weekly Report Generation Failed</h2>
                <p><strong>Build:</strong> #${BUILD_NUMBER}</p>
                <p><strong>Status:</strong> FAILED</p>
                
                <p>Check the console output: <a href="${BUILD_URL}console">${BUILD_URL}console</a></p>
                """,
                mimeType: 'text/html',
                to: 'eranp@radware.com'
            )
        }
    }
}
