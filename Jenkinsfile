pipeline {
    agent { label 'built-in' }
    
    triggers {
        // Run every Monday at 9:00 AM
        cron('0 9 * * 1')
    }
    
    environment {
        // Release version to track
        VERSION = '10.13.0.0'
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
        
        stage('Generate Weekly Report') {
            steps {
                script {
                    def timestamp = new Date().format('yyyy-MM-dd_HHmm')
                    echo "Generating weekly report for version ${VERSION}"
                    
                    // Credentials can be provided either via:
                    // 1. Jenkins credentials (jira-url, jira-email, jira-api-token)
                    // 2. .env file in the workspace
                    
                    // Try to use Jenkins credentials if available, otherwise fall back to .env
                    def hasCredentials = true
                    try {
                        withCredentials([
                            string(credentialsId: 'jira-url', variable: 'JIRA_URL'),
                            string(credentialsId: 'jira-email', variable: 'JIRA_EMAIL'),
                            string(credentialsId: 'jira-api-token', variable: 'JIRA_API_TOKEN')
                        ]) {
                            if (isUnix()) {
                                sh '''
                                    . venv/bin/activate
                                    python3 weekly_work_summary.py
                                '''
                            } else {
                                bat '''
                                    call venv\\Scripts\\activate.bat
                                    python weekly_work_summary.py
                                '''
                            }
                        }
                    } catch (Exception e) {
                        echo "Jenkins credentials not found, using .env file instead"
                        if (isUnix()) {
                            sh '''
                                . venv/bin/activate
                                python3 weekly_work_summary.py
                            '''
                        } else {
                            bat '''
                                call venv\\Scripts\\activate.bat
                                python weekly_work_summary.py
                            '''
                        }
                    }
                }
            }
        }
        
        stage('Archive Reports') {
            steps {
                // Archive HTML and CSV reports as Jenkins artifacts
                archiveArtifacts artifacts: '**/*.html, **/*.csv', 
                                 allowEmptyArchive: false,
                                 fingerprint: true,
                                 onlyIfSuccessful: true
            }
        }
        
        stage('Publish Reports') {
            steps {
                // Publish HTML reports for viewing in Jenkins
                publishHTML([
                    allowMissing: false,
                    alwaysLinkToLastBuild: true,
                    keepAll: true,
                    reportDir: '.',
                    reportFiles: 'weekly_work_summary_*.html',
                    reportName: 'Weekly Work Summary',
                    reportTitles: 'DefensePro Weekly Report'
                ])
            }
        }
        
        stage('Email Notification') {
            steps {
                script {
                    def reportDate = new Date().format('MMMM dd, yyyy')
                    
                    emailext(
                        subject: "DefensePro ${VERSION} - Weekly Report (${reportDate})",
                        body: """
                        <h2>DefensePro Weekly Status Report</h2>
                        <p><strong>Release Version:</strong> ${VERSION}</p>
                        <p><strong>Report Date:</strong> ${reportDate}</p>
                        <p><strong>Build:</strong> #${BUILD_NUMBER}</p>
                        
                        <h3>Reports Generated:</h3>
                        <ul>
                            <li><a href="${BUILD_URL}Weekly_20Work_20Summary/">Weekly Work Summary</a></li>
                            <li><a href="${BUILD_URL}artifact/">Download Artifacts (HTML/CSV)</a></li>
                        </ul>
                        
                        <p>View full details in Jenkins: <a href="${BUILD_URL}">${BUILD_URL}</a></p>
                        
                        <hr>
                        <p><em>Automated report generated by Jenkins</em></p>
                        """,
                        mimeType: 'text/html',
                        to: 'eranp@radware.com',
                        attachmentsPattern: '**/weekly_work_summary_*.html, **/weekly_work_summary_*.csv',
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
