#!/usr/bin/env python3

import gitlab
import requests
import getpass
import time
import sys
from typing import Dict, Any, List

# --- SCRIPT CONFIGURATION ---

GITLAB_GROUP_NAME = "envathon"
SONARQUBE_QUALITY_GATE_NAME = "envathon-gate"
# Use the Docker service name for container-to-container communication
WEBHOOK_TARGET_BASE_URL = "http://webhook-handler:8001/webhooks"

# Define the projects to be created
# Using triple single quotes ''' for file content to avoid conflicts with double quotes inside the code.
PROJECTS = {
    "java-project": {
        "language": "Java",
        "files": {
            "src/main/java/com/envathon/Calculator.java": '''
package com.envathon;

/**
 * A simple calculator with intentional complexities for SonarQube analysis.
 */
public class Calculator {

    /**
     * Adds two numbers.
     * @param a First number.
     * @param b Second number.
     * @return The sum.
     */
    public int add(int a, int b) {
        return a + b;
    }

    /**
     * Subtracts two numbers.
     * @param a First number.
     * @param b Second number.
     * @return The difference.
     */
    public int subtract(int a, int b) {
        return a - b;
    }

    /**
     * Divides two numbers. Contains a potential bug (division by zero).
     * @param a Numerator.
     * @param b Denominator.
     * @return The result of the division.
     */
    public double divide(int a, int b) {
        // This will be flagged by SonarQube
        if (b == 0) {
            System.out.println("Warning: Division by zero.");
            // Returning a sentinel value is better than throwing an exception in some contexts,
            // but can be a code smell.
            return Double.NaN;
        }
        return (double) a / b;
    }

    /**
     * A complex method with high cyclomatic complexity for analysis.
     */
    public void complexMethod(int value) {
        if (value > 0) {
            if (value % 2 == 0) {
                System.out.println("Positive and Even");
            } else {
                System.out.println("Positive and Odd");
            }
        } else if (value < 0) {
            System.out.println("Negative");
        } else {
            for (int i = 0; i < 5; i++) {
                // This loop adds cognitive complexity
                System.out.println("Value is zero, looping: " + i);
            }
        }
    }
}
''',
            "pom.xml": '''
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.envathon</groupId>
    <artifactId>java-project</artifactId>
    <version>1.0.0</version>
    <properties>
        <maven.compiler.source>11</maven.compiler.source>
        <maven.compiler.target>11</maven.compiler.target>
    </properties>
</project>
''',
            "Dockerfile": '''
FROM openjdk:11-jre-slim
WORKDIR /app
COPY target/java-project-1.0.0.jar .
CMD ["java", "-jar", "java-project-1.0.0.jar"]
'''
        }
    },
    "python-project": {
        "language": "Python",
        "files": {
            "app/main.py": '''
import os

class DataProcessor:
    def __init__(self, data):
        self.data = data
        self.processed = False

    def process_data(self):
        """
        Processes data with some complexity and a duplicated block.
        """
        if not self.data:
            print("No data to process.")
            return None

        # This block is intentionally duplicated for SonarQube to find
        if len(self.data) > 10:
            print("Large dataset detected.")
        else:
            print("Small dataset detected.")

        result = [item * 2 for item in self.data]
        self.processed = True
        return result

    def another_complex_function(self, x, y, z):
        """
        A function with high cognitive complexity.
        """
        if x > y:
            if y > z:
                return "Path 1"
            else:
                return "Path 2"
        elif x < y:
            # This block is also intentionally duplicated
            if len(self.data) > 10:
                print("Large dataset detected.")
            else:
                print("Small dataset detected.")
            return "Path 3"
        else:
            # Unused variable 'secret'
            secret = os.getenv("SECRET_KEY_NOT_SET")
            return "Path 4"

def main():
    processor = DataProcessor([1, 2, 3, 4, 5])
    processor.process_data()
    processor.another_complex_function(5, 3, 1)

if __name__ == "__main__":
    main()
''',
            "requirements.txt": "requests\n",
            "Dockerfile": '''
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ .
CMD ["python", "main.py"]
'''
        }
    },
    "javascript-project": {
        "language": "JavaScript",
        "files": {
            "index.js": '''
const express = require('express');
const app = express();
const port = 3000;

// This function has a code smell: password is logged.
function checkUser(username, password) {
    console.log(`Checking user: ${username} with password: ${password}`);
    if (!password) {
        // This will never be true if password is required, creating dead code.
        return false;
    }
    return true;
}

app.get('/', (req, res) => {
    // A long and complex regular expression
    const complexRegex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\\d)(?=.*[@$!%*?&])[A-Za-z\\d@$!%*?&]{8,}$/;
    const testString = "Password123!";

    if (complexRegex.test(testString)) {
        res.send('Hello World from a complex JS project!');
    } else {
        res.send('Regex failed.');
    }
});

// Duplicated code block
app.get('/status', (req, res) => {
    const health = { status: 'ok', timestamp: new Date() };
    res.json(health);
});

app.get('/health', (req, res) => {
    const health = { status: 'ok', timestamp: new Date() };
    res.json(health);
});


app.listen(port, () => {
    console.log(`Example app listening at http://localhost:${port}`);
    checkUser('admin', 's3cr3tP@ssw0rd');
});
''',
            "package.json": '''
{
  "name": "javascript-project",
  "version": "1.0.0",
  "description": "",
  "main": "index.js",
  "scripts": {
    "start": "node index.js"
  },
  "dependencies": {
    "express": "^4.17.1"
  }
}
''',
            "Dockerfile": '''
FROM node:16
WORKDIR /usr/src/app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 3000
CMD [ "node", "index.js" ]
'''
        }
    }
}

# --- SHARED CI/CD TEMPLATE ---
SHARED_CI_TEMPLATE = {
    "templates.yml": '''
# Shared CI/CD templates for all projects in the envathon group

variables:
  DOCKER_HOST: tcp://docker:2376
  DOCKER_TLS_CERTDIR: "/certs"
  DOCKER_TLS_VERIFY: 1
  DOCKER_CERT_PATH: "$DOCKER_TLS_CERTDIR/client"
  SONAR_USER_HOME: "${CI_PROJECT_DIR}/.sonar"
  GIT_DEPTH: "0"

.docker-build-template:
  image: docker:24.0.5
  stage: build
  services:
    - docker:24.0.5-dind
  tags:
    - docker
  before_script:
    - until docker info; do sleep 1; done
  script:
    - echo "Building Docker image for ${CI_PROJECT_NAME}..."
    - docker build -t ${CI_PROJECT_NAME}:${CI_COMMIT_SHORT_SHA} .
    - echo "Docker build complete."

.sonar-scan-template:
  image: sonarsource/sonar-scanner-cli:latest
  stage: quality_scan
  tags:
    - docker
  cache:
    key: "${CI_JOB_NAME}"
    paths:
      - .sonar/cache
  script:
    - >
      sonar-scanner
      -Dsonar.qualitygate.wait=true
      -Dsonar.projectKey=${SONAR_PROJECT_KEY}
      -Dsonar.host.url=${SONAR_HOST_URL}
      -Dsonar.token=${SONAR_TOKEN}
      -Dsonar.sources=.
  allow_failure: false
'''
}

# --- SONARQUBE QUALITY GATE RULES ---
# These are strict rules for the custom quality gate.
# Find metric keys in your SonarQube instance under Quality Gates -> Create -> Add Condition
STRICT_QUALITY_GATE_CONDITIONS = [
    {"metric": "new_reliability_rating", "op": "GT", "error": "1"}, # Rating must be A (1)
    {"metric": "new_security_rating", "op": "GT", "error": "1"},    # Rating must be A (1)
    {"metric": "new_maintainability_rating", "op": "GT", "error": "1"}, # Rating must be A (1)
    {"metric": "new_coverage", "op": "LT", "error": "80"},
    {"metric": "new_duplicated_lines_density", "op": "GT", "error": "3"},
    {"metric": "new_code_smells", "op": "GT", "error": "5"},
    {"metric": "new_vulnerabilities", "op": "GT", "error": "0"},
    {"metric": "new_bugs", "op": "GT", "error": "0"},
]

# --- HELPER FUNCTIONS ---
def print_info(message):
    print(f"\033[94m[INFO]\033[0m {message}")

def print_success(message):
    print(f"\033[92m[SUCCESS]\033[0m {message}")

def print_warning(message):
    print(f"\033[93m[WARNING]\033[0m {message}")

def print_error(message):
    print(f"\033[91m[ERROR]\033[0m {message}", file=sys.stderr)
    sys.exit(1)

# --- API MANAGER CLASSES ---

class SonarQubeManager:
    """Handles all interactions with the SonarQube API."""
    def __init__(self, url: str, token: str):
        self.url = url.rstrip('/')
        self.session = requests.Session()
        self.session.auth = (token, '')

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """
        Helper to make requests. It will raise an HTTPError for bad responses (4xx or 5xx),
        which can be caught by the calling function.
        """
        try:
            response = self.session.request(method, f"{self.url}/api/{endpoint}", **kwargs)
            # Raise an exception for bad status codes (4xx or 5xx)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            # Print a more detailed warning before re-raising the exception
            if e.response is not None:
                try:
                    error_data = e.response.json()
                    errors = error_data.get('errors', [])
                    error_msg = ', '.join([err['msg'] for err in errors]) if errors else e.response.text
                    print_warning(f"SonarQube API Error on {method} {endpoint}: {e.response.status_code} - {error_msg}")
                except requests.exceptions.JSONDecodeError:
                    print_warning(f"SonarQube API Error on {method} {endpoint}: {e.response.status_code} - {e.response.text}")
            raise e # Re-raise the exception to be handled by the caller
        except requests.exceptions.RequestException as e:
            print_error(f"A fatal SonarQube request failed: {e}")


    def cleanup(self):
        """Deletes all artifacts created by this script. Handles 404s gracefully."""
        print_info("--- Starting SonarQube Cleanup ---")
        
        # Delete Quality Gate
        print_info(f"Attempting to delete Quality Gate '{SONARQUBE_QUALITY_GATE_NAME}'...")
        try:
            self._request('POST', 'qualitygates/destroy', params={'name': SONARQUBE_QUALITY_GATE_NAME})
            print_success(f"Quality Gate '{SONARQUBE_QUALITY_GATE_NAME}' deleted.")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                print_info("Quality Gate did not exist, skipping.")
            else:
                # For any other error (e.g., 401 Unauthorized), we should stop.
                print_error(f"An unexpected SonarQube error occurred during quality gate deletion: {e}")

        # Delete Projects
        for project_key in PROJECTS:
            sonar_project_key = f"{GITLAB_GROUP_NAME}_{project_key}"
            print_info(f"Attempting to delete project '{sonar_project_key}'...")
            try:
                self._request('POST', 'projects/delete', params={'project': sonar_project_key})
                print_success(f"Project '{sonar_project_key}' deleted.")
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    print_info(f"Project '{sonar_project_key}' did not exist, skipping.")
                else:
                    print_error(f"An unexpected SonarQube error occurred during project deletion: {e}")
        print_info("--- SonarQube Cleanup Complete ---")


    def setup_quality_gate(self):
        """Creates and configures the custom quality gate idempotently."""
        print_info(f"Ensuring Quality Gate '{SONARQUBE_QUALITY_GATE_NAME}' exists...")
        try:
            self._request('POST', 'qualitygates/create', params={'name': SONARQUBE_QUALITY_GATE_NAME})
            print_success(f"Quality Gate '{SONARQUBE_QUALITY_GATE_NAME}' created.")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400 and 'already exists' in e.response.text:
                 print_warning(f"Quality Gate '{SONARQUBE_QUALITY_GATE_NAME}' already exists. Resetting it.")
            else:
                raise e

        # --- New Logic: Clear existing conditions to ensure a clean slate ---
        print_info(f"Clearing any existing conditions from gate '{SONARQUBE_QUALITY_GATE_NAME}'...")
        try:
            response = self._request('GET', 'qualitygates/show', params={'name': SONARQUBE_QUALITY_GATE_NAME})
            gate_data = response.json()
            existing_conditions = gate_data.get('conditions', [])

            for cond in existing_conditions:
                # Defensive checks for unexpected API response structure
                if not isinstance(cond, dict):
                    print_warning(f"  - Skipping unexpected item in conditions list: {cond}")
                    continue
                
                cond_id = cond.get('id')
                if not cond_id:
                    print_warning(f"  - Skipping condition with no ID: {cond}")
                    continue

                metric_info = cond.get('metric', {})
                metric_key = 'unknown'
                if isinstance(metric_info, dict):
                    metric_key = metric_info.get('key', 'unknown')

                print_info(f"  - Deleting existing condition for metric '{metric_key}' (ID: {cond_id})...")
                self._request('POST', 'qualitygates/delete_condition', params={'id': cond_id})
            print_success("All existing conditions cleared.")

        except requests.exceptions.HTTPError as e:
            print_error(f"Failed to clear existing conditions from quality gate: {e}")
        except Exception as e:
            print_error(f"An unexpected error occurred while clearing conditions: {e}")


        print_info("Setting strict conditions on quality gate...")
        for cond in STRICT_QUALITY_GATE_CONDITIONS:
            params = {
                'gateName': SONARQUBE_QUALITY_GATE_NAME,
                'metric': cond['metric'],
                'op': cond['op'],
                'error': cond['error']
            }
            try:
                self._request('POST', 'qualitygates/create_condition', params=params)
                print_info(f"  - Added condition: {cond['metric']} {cond['op']} {cond['error']}")
            except requests.exceptions.HTTPError as e:
                # This block should ideally not be hit now, but is kept as a safeguard.
                print_error(f"Failed to create condition for metric '{cond['metric']}': {e}")
        print_success("All quality gate conditions set.")

    def create_project(self, name: str, key: str):
        """Creates a project in SonarQube and sets its quality gate."""
        print_info(f"Creating SonarQube project '{name}' with key '{key}'...")
        try:
            self._request('POST', 'projects/create', params={'name': name, 'project': key})
            print_success(f"SonarQube project '{name}' created.")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                print_warning(f"SonarQube project '{key}' may already exist. Continuing.")
            else:
                raise e
        
        print_info(f"Assigning '{SONARQUBE_QUALITY_GATE_NAME}' to project '{key}'...")
        self._request('POST', 'qualitygates/select', params={'projectKey': key, 'gateName': SONARQUBE_QUALITY_GATE_NAME})

        print_info(f"Setting up webhook for project '{key}'...")
        webhook_url = f"{WEBHOOK_TARGET_BASE_URL}/sonarqube"
        try:
            self._request('POST', 'webhooks/create', params={'name': 'Generic Notification', 'project': key, 'url': webhook_url})
            print_success(f"Webhook created for project '{key}'.")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400 and 'already exists' in e.response.text:
                print_warning(f"Webhook for project '{key}' already exists. Skipping.")
            else:
                raise e
        print_success(f"SonarQube project '{name}' successfully configured.")


class GitLabManager:
    """Handles all interactions with the GitLab API."""
    def __init__(self, url: str, token: str):
        try:
            self.gl = gitlab.Gitlab(url, private_token=token, timeout=30)
            self.gl.auth()
            print_success("Successfully authenticated with GitLab API.")
        except gitlab.exceptions.GitlabAuthenticationError:
            print_error("GitLab authentication failed. Please check your URL and token.")
        except Exception as e:
            print_error(f"Failed to connect to GitLab at {url}. Error: {e}")

    def cleanup(self):
        """Finds and permanently deletes the main group."""
        print_info("--- Starting GitLab Cleanup ---")
        try:
            groups = self.gl.groups.list(search=GITLAB_GROUP_NAME)
            if not groups:
                print_info(f"Group '{GITLAB_GROUP_NAME}' not found. Skipping deletion.")
                return

            group = groups[0]
            print_info(f"Found group '{GITLAB_GROUP_NAME}' (ID: {group.id}). Deleting...")
            
            # This is the key for permanent deletion. GitLab API v4 requires this.
            # We must un-soft-delete it first if it's in that state.
            # The python-gitlab library doesn't directly support this, so we use a raw query.
            # However, the simple delete should work for most self-hosted setups if admin.
            # For gitlab.com, you might need to use the API to delete it permanently.
            group.delete()
            
            print_info(f"Deletion request sent for group '{GITLAB_GROUP_NAME}'. Waiting for it to be fully removed...")
            
            # Wait until the group is actually gone
            max_wait_seconds = 120
            start_time = time.time()
            while time.time() - start_time < max_wait_seconds:
                if not self.gl.groups.list(search=GITLAB_GROUP_NAME):
                    print_success(f"Group '{GITLAB_GROUP_NAME}' has been permanently deleted.")
                    print_info("--- GitLab Cleanup Complete ---")
                    return
                time.sleep(5)
                print_info("...still waiting for group to be deleted...")

            print_warning("Group was not deleted within the timeout period. It might be in a 'pending' deletion state. Please check the GitLab UI.")

        except gitlab.exceptions.GitlabError as e:
            print_error(f"An error occurred during GitLab cleanup: {e}")


    def create_group(self, sonar_token: str):
        """Creates the main group and sets group-level variables."""
        print_info(f"Creating GitLab group '{GITLAB_GROUP_NAME}'...")
        group = self.gl.groups.create({'name': GITLAB_GROUP_NAME, 'path': GITLAB_GROUP_NAME})
        print_success(f"Group '{GITLAB_GROUP_NAME}' created at: {group.web_url}")

        print_info("Setting group-level CI/CD variables...")
        group.variables.create({
            'key': 'SONAR_HOST_URL',
            'value': sonar_manager.url,
            'variable_type': 'env_var',
            'protected': False
        })
        group.variables.create({
            'key': 'SONAR_TOKEN',
            'value': sonar_token,
            'variable_type': 'env_var',
            'protected': False,
            'masked': True
        })
        print_success("Group variables 'SONAR_HOST_URL' and 'SONAR_TOKEN' set.")
        return group

    def create_project(self, group, name: str, description: str = ""):
        """Creates a project within the specified group."""
        print_info(f"Creating project '{name}' in group '{group.name}'...")
        project = self.gl.projects.create({
            'name': name,
            'namespace_id': group.id,
            'description': description,
            'initialize_with_readme': True # Creates a main branch
        })
        print_success(f"Project '{name}' created: {project.web_url}")
        return project

    def commit_files_to_project(self, project, files: Dict[str, str], message: str):
        """Commits a dictionary of files to a project."""
        print_info(f"Committing files to '{project.name}'...")
        actions = [
            {'action': 'create', 'file_path': path, 'content': content}
            for path, content in files.items()
        ]
        data = {
            'branch': 'main',
            'commit_message': message,
            'actions': actions
        }
        project.commits.create(data)
        print_success(f"Initial commit pushed to '{project.name}'.")

    def setup_project_integrations(self, project):
        """Sets project-level variables and webhooks."""
        # Set project-specific SonarQube key
        sonar_project_key = f"{GITLAB_GROUP_NAME}_{project.name}"
        print_info(f"Setting 'SONAR_PROJECT_KEY' for '{project.name}'...")
        project.variables.create({
            'key': 'SONAR_PROJECT_KEY',
            'value': sonar_project_key,
            'variable_type': 'env_var'
        })

        # Set GitLab webhook
        print_info(f"Setting up GitLab webhook for '{project.name}'...")
        webhook_url = f"{WEBHOOK_TARGET_BASE_URL}/gitlab"
        project.hooks.create({
            'url': webhook_url,
            'push_events': True,
            'merge_requests_events': True,
            'pipeline_events': True,
            'job_events': True,
            'note_events': True,
        })
        print_success(f"Integrations configured for '{project.name}'.")

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    print_info("--- GitLab and SonarQube Environment Setup Script ---")
    print_warning("This script will DESTROY and RECREATE the specified GitLab group and SonarQube projects.")
    if input("Are you sure you want to continue? (yes/no): ").lower() != 'yes':
        print_info("Operation cancelled.")
        sys.exit(0)

    # --- Get User Credentials ---
    gitlab_url = input("Enter GitLab URL [http://localhost:8080]: ") or "http://localhost:8080"
    gitlab_token = getpass.getpass("Enter GitLab Private Access Token (scope: api): ")
    sonarqube_url = input("Enter SonarQube URL [http://localhost:9001]: ") or "http://localhost:9001"
    sonarqube_token = getpass.getpass("Enter SonarQube User Token: ")

    if not all([gitlab_token, sonarqube_token]):
        print_error("GitLab and SonarQube tokens are required.")

    # --- Initialize API Managers ---
    print_info("Initializing API clients...")
    gitlab_manager = GitLabManager(gitlab_url, gitlab_token)
    sonar_manager = SonarQubeManager(sonarqube_url, sonarqube_token)

    # --- Execute Cleanup and Setup ---
    try:
        # 1. Cleanup Phase (Idempotency)
        gitlab_manager.cleanup()
        sonar_manager.cleanup()

        # 2. Setup SonarQube
        print_info("\n--- Starting SonarQube Setup ---")
        sonar_manager.setup_quality_gate()

        # 3. Setup GitLab Group
        print_info("\n--- Starting GitLab Setup ---")
        envathon_group = gitlab_manager.create_group(sonarqube_token)

        # 4. Create Shared CI/CD Project
        print_info("\n--- Setting up Shared CI/CD Project ---")
        shared_ci_project = gitlab_manager.create_project(
            envathon_group,
            "shared-ci-cd",
            "Stores shared CI/CD templates for the envathon group."
        )
        gitlab_manager.commit_files_to_project(
            shared_ci_project,
            SHARED_CI_TEMPLATE,
            "feat: add initial CI templates"
        )

        # 5. Create Application Projects
        for project_name, config in PROJECTS.items():
            print_info(f"\n--- Setting up Application Project: {project_name} ---")
            
            # Create SonarQube project first
            sonar_project_key = f"{GITLAB_GROUP_NAME}_{project_name}"
            sonar_manager.create_project(project_name, sonar_project_key)

            # Create GitLab project
            app_project = gitlab_manager.create_project(
                envathon_group,
                project_name,
                f"A sample {config['language']} project."
            )

            # Add .gitlab-ci.yml to the files to be committed
            ci_file_content = f"""
include:
  - project: '{GITLAB_GROUP_NAME}/shared-ci-cd'
    ref: main
    file: '/templates.yml'

stages:
  - build
  - quality_scan

build-job:
  extends: .docker-build-template

sonar-scan-job:
  extends: .sonar-scan-template
"""
            files_to_commit = config['files'].copy()
            files_to_commit['.gitlab-ci.yml'] = ci_file_content

            # Commit project code and CI file
            gitlab_manager.commit_files_to_project(
                app_project,
                files_to_commit,
                f"feat: initial commit for {config['language']} application"
            )

            # Configure variables and webhooks
            gitlab_manager.setup_project_integrations(app_project)
        
        print_success("\n\n--- SETUP COMPLETE! ---")
        print_info(f"GitLab group '{GITLAB_GROUP_NAME}' is available at: {envathon_group.web_url}")
        print_info("You can now go to a project's CI/CD -> Pipelines section and run a pipeline on the 'main' branch.")

    except Exception as e:
        print_error(f"An unexpected error occurred during setup: {e}")