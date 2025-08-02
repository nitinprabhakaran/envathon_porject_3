#!/usr/bin/env python3
"""
Simplified CI/CD Demo Environment Setup Script
Creates GitLab projects with focused failure scenarios:
- 1 project with SonarQube quality gate failure
- 3 projects with different pipeline failures
"""

import gitlab
import requests
import json
import time
import getpass
import sys
from typing import Dict, Any, List, Optional
from datetime import datetime

# Configuration
GROUP_NAME = "cicd-demo"
QUALITY_GATE_NAME = "demo-quality-gate"
AGENT_WEBHOOK_URL = "http://strands-agent:8000/webhooks"

# Color codes for output
class Colors:
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'

def info(msg: str):
    print(f"{Colors.BLUE}[INFO]{Colors.END} {msg}")

def success(msg: str):
    print(f"{Colors.GREEN}[SUCCESS]{Colors.END} {msg}")

def warning(msg: str):
    print(f"{Colors.YELLOW}[WARNING]{Colors.END} {msg}")

def error(msg: str):
    print(f"{Colors.RED}[ERROR]{Colors.END} {msg}")
    sys.exit(1)

# Namespace-level (Group) CI/CD Variables
NAMESPACE_VARIABLES = [
    # Docker and Registry
    {'key': 'DOCKER_DRIVER', 'value': 'overlay2'},
    {'key': 'DOCKER_TLS_CERTDIR', 'value': ''},
    
    # SonarQube
    {'key': 'SONAR_HOST_URL', 'value': 'http://sonarqube:9000'},
    {'key': 'SONAR_TOKEN', 'value': 'sonar_token_placeholder', 'masked': True},
    
    # Common settings
    {'key': 'GIT_DEPTH', 'value': '0'},
]

# Project-specific variables
PROJECT_VARIABLES = {
    "quality-demo": [
        {'key': 'SONAR_PROJECT_KEY', 'value': 'quality-demo'},
    ],
    "python-api": [
        {'key': 'PYTHON_VERSION', 'value': '3.9'},
    ],
    "java-service": [
        {'key': 'JAVA_VERSION', 'value': '11'},
    ],
    "node-app": [
        {'key': 'NODE_VERSION', 'value': '16'},
    ],
}

# Shared CI/CD template (simplified)
SHARED_TEMPLATE = """
stages:
  - build
  - test
  - quality
  - package

variables:
  DOCKER_DRIVER: overlay2
  GIT_DEPTH: "0"

# Java template
.java-build:
  stage: build
  image: maven:3.8-openjdk-11
  script:
    - mvn clean compile
  artifacts:
    paths:
      - target/
    expire_in: 1 hour

.java-test:
  stage: test
  image: maven:3.8-openjdk-11
  script:
    - mvn test
  artifacts:
    reports:
      junit:
        - target/surefire-reports/TEST-*.xml

# Python template
.python-build:
  stage: build
  image: python:3.9
  script:
    - pip install -r requirements.txt
    - python -m py_compile *.py

.python-test:
  stage: test
  image: python:3.9
  script:
    - pip install pytest
    - pytest

# Node template
.node-build:
  stage: build
  image: node:16
  script:
    - npm ci

.node-test:
  stage: test
  image: node:16
  script:
    - npm test

# SonarQube template
.sonarqube-check:
  stage: quality
  image: sonarsource/sonar-scanner-cli:latest
  script:
    - sonar-scanner 
      -Dsonar.projectKey=${SONAR_PROJECT_KEY}
      -Dsonar.sources=.
      -Dsonar.host.url=$SONAR_HOST_URL 
      -Dsonar.login=$SONAR_TOKEN
      -Dsonar.qualitygate.wait=true
"""

# Project definitions with minimal code
PROJECTS = {
    # 1. SonarQube Quality Gate Failure
    "quality-demo": {
        "description": "Java project with quality issues",
        "language": "java",
        "files": {
            "src/main/java/demo/App.java": """
package demo;

import java.sql.*;

public class App {
    private static final String PASSWORD = "admin123"; // Security issue
    
    public void processData(String input) throws SQLException {
        // SQL Injection vulnerability
        String query = "SELECT * FROM users WHERE name = '" + input + "'";
        Connection conn = DriverManager.getConnection("jdbc:h2:mem:test", "sa", PASSWORD);
        Statement stmt = conn.createStatement();
        ResultSet rs = stmt.executeQuery(query);
        // Resources not closed - memory leak
    }
    
    // Duplicate code (code smell)
    public int calculate1(int x) {
        if (x > 10) {
            return x * 2;
        }
        return x;
    }
    
    public int calculate2(int x) {
        if (x > 10) {
            return x * 2;
        }
        return x;
    }
}
""",
            "pom.xml": """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 
         https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    
    <groupId>com.demo</groupId>
    <artifactId>quality-demo</artifactId>
    <version>1.0.0</version>
    
    <properties>
        <maven.compiler.source>11</maven.compiler.source>
        <maven.compiler.target>11</maven.compiler.target>
    </properties>
    
    <dependencies>
        <dependency>
            <groupId>com.h2database</groupId>
            <artifactId>h2</artifactId>
            <version>2.1.214</version>
        </dependency>
    </dependencies>
</project>
""",
            ".gitlab-ci.yml": """
include:
  - project: 'cicd-demo/shared-pipeline'
    ref: main
    file: '/shared-template.yml'

build:
  extends: .java-build

test:
  extends: .java-test
  needs: ["build"]

sonarqube-check:
  extends: .sonarqube-check
  needs: ["test"]
"""
        }
    },

    # 2. Python - Runtime Error (Division by Zero)
    "python-api": {
        "description": "Python API with runtime error",
        "language": "python",
        "files": {
            "app.py": """
def calculate_average(numbers):
    total = sum(numbers)
    # Bug: doesn't check for empty list
    return total / len(numbers)

def process_data(data):
    results = []
    for item in data:
        # Will fail when item['values'] is empty
        avg = calculate_average(item['values'])
        results.append({
            'id': item['id'],
            'average': avg
        })
    return results

def main():
    test_data = [
        {'id': 1, 'values': [10, 20, 30]},
        {'id': 2, 'values': []},  # This will cause division by zero
        {'id': 3, 'values': [15, 25]}
    ]
    
    results = process_data(test_data)
    print(f"Processed {len(results)} items")
    return results

if __name__ == "__main__":
    main()
""",
            "test_app.py": """
import pytest
from app import calculate_average, process_data, main

def test_calculate_average_normal():
    assert calculate_average([10, 20, 30]) == 20

def test_process_data_with_empty():
    # This test will fail due to division by zero
    data = [{'id': 1, 'values': []}]
    result = process_data(data)
    assert len(result) == 1

def test_main():
    # This will also fail
    main()
""",
            "requirements.txt": """pytest==7.4.0
""",
            ".gitlab-ci.yml": """
include:
  - project: 'cicd-demo/shared-pipeline'
    ref: main
    file: '/shared-template.yml'

build:
  extends: .python-build

test:
  extends: .python-test
  needs: ["build"]
"""
        }
    },

    # 3. Java - Compilation Error (Missing Class)
    "java-service": {
        "description": "Java service with compilation error",
        "language": "java",
        "files": {
            "src/main/java/demo/Service.java": """
package demo;

public class Service {
    private DatabaseHelper dbHelper; // This class doesn't exist
    
    public Service() {
        this.dbHelper = new DatabaseHelper(); // Compilation error
    }
    
    public String getData(int id) {
        return dbHelper.fetchById(id); // Will fail to compile
    }
    
    public static void main(String[] args) {
        Service service = new Service();
        System.out.println("Service started");
    }
}
""",
            "src/main/java/demo/Main.java": """
package demo;

public class Main {
    public static void main(String[] args) {
        System.out.println("Application starting...");
        Service service = new Service();
        service.getData(1);
    }
}
""",
            "pom.xml": """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 
         https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    
    <groupId>com.demo</groupId>
    <artifactId>java-service</artifactId>
    <version>1.0.0</version>
    
    <properties>
        <maven.compiler.source>11</maven.compiler.source>
        <maven.compiler.target>11</maven.compiler.target>
    </properties>
</project>
""",
            ".gitlab-ci.yml": """
include:
  - project: 'cicd-demo/shared-pipeline'
    ref: main
    file: '/shared-template.yml'

build:
  extends: .java-build
  # Will fail due to missing DatabaseHelper class

test:
  extends: .java-test
  needs: ["build"]
"""
        }
    },

    # 4. Node.js - Syntax Error
    "node-app": {
        "description": "Node app with syntax error",
        "language": "javascript",
        "files": {
            "server.js": """
const express = require('express');
const app = express();

app.get('/health', (req, res) => {
    res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

app.get('/users/:id', (req, res) => {
    const userId = req.params.id;
    // Syntax error: missing closing bracket
    res.json({ 
        id: userId,
        name: `User ${userId}`,
        createdAt: new Date().toISOString()
    );  // Missing }
});

app.listen(3000, () => {
    console.log('Server running on port 3000');
});
""",
            "test.js": """
const assert = require('assert');

describe('Server Tests', () => {
    it('should load server without errors', () => {
        // This will fail due to syntax error in server.js
        require('./server');
        assert(true);
    });
});
""",
            "package.json": """{
  "name": "node-app",
  "version": "1.0.0",
  "main": "server.js",
  "scripts": {
    "test": "mocha test.js",
    "start": "node server.js"
  },
  "dependencies": {
    "express": "^4.18.2"
  },
  "devDependencies": {
    "mocha": "^10.2.0"
  }
}
""",
            "package-lock.json": """{
  "name": "node-app",
  "version": "1.0.0",
  "lockfileVersion": 2,
  "requires": true,
  "packages": {
    "": {
      "name": "node-app",
      "version": "1.0.0",
      "dependencies": {
        "express": "^4.18.2"
      },
      "devDependencies": {
        "mocha": "^10.2.0"
      }
    }
  }
}
""",
            ".gitlab-ci.yml": """
include:
  - project: 'cicd-demo/shared-pipeline'
    ref: main
    file: '/shared-template.yml'

build:
  extends: .node-build

test:
  extends: .node-test
  needs: ["build"]
  # Will fail due to syntax error in server.js
"""
        }
    }
}

class GitLabSetup:
    def __init__(self, url: str, token: str):
        self.gl = gitlab.Gitlab(url, private_token=token)
        self.gl.auth()
        success("Connected to GitLab")
        
    def cleanup(self):
        """Remove existing group if it exists"""
        info(f"Cleaning up existing '{GROUP_NAME}' group...")
        try:
            groups = self.gl.groups.list(search=GROUP_NAME)
            if groups:
                groups[0].delete()
                time.sleep(3)
            success("Cleanup complete")
        except Exception as e:
            warning(f"Cleanup warning: {e}")
            
    def create_environment(self):
        """Create complete GitLab environment"""
        # Create group
        info(f"Creating group '{GROUP_NAME}'...")
        group = self.gl.groups.create({
            'name': GROUP_NAME,
            'path': GROUP_NAME,
            'description': 'Simplified CI/CD demo with focused failure scenarios'
        })
        
        # Set namespace-level CI/CD variables
        info("Setting namespace-level CI/CD variables...")
        for var in NAMESPACE_VARIABLES:
            try:
                if var['key'] == 'SONAR_TOKEN' and hasattr(self, 'sonar_token'):
                    var['value'] = self.sonar_token
                group.variables.create(var)
                info(f"  Added namespace variable: {var['key']}")
            except Exception as e:
                warning(f"  Failed to add namespace variable {var['key']}: {e}")
        
        # Create shared pipeline project
        info("Creating shared pipeline repository...")
        shared_project = self.gl.projects.create({
            'name': 'shared-pipeline',
            'namespace_id': group.id,
            'description': 'Shared CI/CD pipeline template'
        })
        
        # Commit shared template
        self._commit_files(shared_project, {"shared-template.yml": SHARED_TEMPLATE}, "feat: Add shared template")
        
        # Create application projects
        for project_name, config in PROJECTS.items():
            info(f"Creating project '{project_name}' ({config['language']})...")
            project = self.gl.projects.create({
                'name': project_name,
                'namespace_id': group.id,
                'description': config['description']
            })
            
            # Set project-specific variables
            info(f"  Setting project-level variables for {project_name}...")
            if project_name in PROJECT_VARIABLES:
                for var in PROJECT_VARIABLES[project_name]:
                    try:
                        project.variables.create(var)
                        info(f"    Added variable: {var['key']} = {var['value'][:20]}...")
                    except Exception as e:
                        warning(f"    Failed to add variable {var['key']}: {e}")
            
            # Create webhook
            try:
                project.hooks.create({
                    'url': f"{AGENT_WEBHOOK_URL}/gitlab",
                    'pipeline_events': True,
                    'push_events': False,
                    'merge_requests_events': True
                })
                info(f"  Added webhook for {project_name}")
            except:
                pass
            
            # Commit files
            self._commit_files(project, config['files'], f"Initial commit: {config['description']}")
            
        success(f"GitLab environment created: {group.web_url}")
        return group
        
    def _commit_files(self, project, files: Dict[str, str], message: str):
        """Commit multiple files to a project"""
        actions = []
        for file_path, content in files.items():
            actions.append({
                'action': 'create',
                'file_path': file_path,
                'content': content
            })
        
        project.commits.create({
            'branch': 'main',
            'commit_message': message,
            'actions': actions
        })

class SonarQubeSetup:
    def __init__(self, url: str, token: str):
        self.url = url.rstrip('/')
        self.session = requests.Session()
        self.session.auth = (token, '')
        success("Connected to SonarQube")
        
    def cleanup(self):
        """Remove existing quality gate and projects"""
        info("Cleaning up SonarQube...")
        
        # Delete quality gate
        try:
            response = self.session.post(
                f"{self.url}/api/qualitygates/destroy",
                params={'name': QUALITY_GATE_NAME}
            )
        except:
            pass
            
        # Delete all projects that might exist
        project_keys = list(PROJECTS.keys()) + [f"{GROUP_NAME}_{p}" for p in PROJECTS.keys()]
        for project_key in project_keys:
            try:
                response = self.session.post(
                    f"{self.url}/api/projects/delete",
                    params={'project': project_key}
                )
                if response.status_code == 204:
                    info(f"  Deleted SonarQube project: {project_key}")
            except:
                pass
                
        success("SonarQube cleanup complete")
        
    def create_quality_gate(self):
        """Create quality gate with medium strictness"""
        info(f"Creating quality gate '{QUALITY_GATE_NAME}'...")
        
        # Create gate
        response = self.session.post(
            f"{self.url}/api/qualitygates/create",
            params={'name': QUALITY_GATE_NAME}
        )
        
        if response.status_code == 400:
            warning("Quality gate already exists")
        else:
            response.raise_for_status()
            
        # Add conditions that will fail for quality-demo project
        conditions = [
            # Bugs
            {'metric': 'bugs', 'op': 'GT', 'error': '0'},
            
            # Vulnerabilities
            {'metric': 'vulnerabilities', 'op': 'GT', 'error': '0'},
            
            # Code Smells
            {'metric': 'code_smells', 'op': 'GT', 'error': '5'},
            
            # Security
            {'metric': 'security_rating', 'op': 'GT', 'error': '1'},
        ]
        
        for condition in conditions:
            try:
                self.session.post(
                    f"{self.url}/api/qualitygates/create_condition",
                    params={
                        'gateName': QUALITY_GATE_NAME,
                        'metric': condition['metric'],
                        'op': condition['op'],
                        'error': condition['error']
                    }
                )
                info(f"  Added condition: {condition['metric']} {condition['op']} {condition['error']}")
            except Exception as e:
                warning(f"  Failed to add condition {condition['metric']}: {e}")
                
        # Set as default
        self.session.post(
            f"{self.url}/api/qualitygates/set_as_default",
            params={'name': QUALITY_GATE_NAME}
        )
        
        success("Quality gate created")
        
    def create_projects(self):
        """Create SonarQube project for quality-demo only"""
        project_key = "quality-demo"
        info(f"Creating SonarQube project '{project_key}'...")
        
        # Create project
        response = self.session.post(
            f"{self.url}/api/projects/create",
            params={
                'name': project_key,
                'project': project_key
            }
        )
        
        if response.status_code != 400:
            response.raise_for_status()
            
        # Create webhook
        self.session.post(
            f"{self.url}/api/webhooks/create",
            params={
                'name': 'CI/CD Assistant',
                'project': project_key,
                'url': f"{AGENT_WEBHOOK_URL}/sonarqube"
            }
        )
        
        success("SonarQube project created")

def print_summary():
    """Print summary of created projects"""
    print("\n" + "="*80)
    success("Demo environment created successfully!")
    
    print("\n📦 PROJECTS CREATED:")
    
    print("\n🚨 SONARQUBE QUALITY GATE FAILURE:")
    print("  • quality-demo: Java project with security issues and code smells")
    print("    - SQL injection vulnerability")
    print("    - Hardcoded password")
    print("    - Resource leak")
    print("    - Duplicate code")
    
    print("\n🔴 PIPELINE FAILURES:")
    print("  • python-api: Runtime error (division by zero in tests)")
    print("  • java-service: Compilation error (missing DatabaseHelper class)")
    print("  • node-app: Syntax error (missing closing bracket)")
    
    print("\n✅ KEY FEATURES:")
    print("  • Minimal code for easy analysis")
    print("  • Clear failure patterns")
    print("  • Different failure types (runtime, compile, syntax)")
    print("  • One SonarQube project for focused demo")
    
    print("\n" + "="*80)

if __name__ == "__main__":
    print("=== Simplified CI/CD Demo Environment Setup ===\n")
    
    # Get credentials
    gitlab_url = input("GitLab URL [http://localhost:8080]: ").strip() or "http://localhost:8080"
    gitlab_token = getpass.getpass("GitLab Token (with api scope): ")
    sonar_url = input("SonarQube URL [http://localhost:9001]: ").strip() or "http://localhost:9001"
    sonar_token = getpass.getpass("SonarQube Token: ")
    
    print(f"\nThis script will create:")
    print(f"- GitLab group '{GROUP_NAME}'")
    print(f"- 4 projects (1 quality, 3 pipeline failures)")
    print(f"- Quality gate for SonarQube")
    print(f"- Webhook integrations")
    
    if input("\nProceed? (yes/no): ").lower() != 'yes':
        print("Cancelled")
        sys.exit(0)
        
    try:
        # Initialize
        gitlab_manager = GitLabSetup(gitlab_url, gitlab_token)
        gitlab_manager.sonar_token = sonar_token
        sonar_manager = SonarQubeSetup(sonar_url, sonar_token)
        
        # Cleanup
        gitlab_manager.cleanup()
        sonar_manager.cleanup()
        
        # Create
        sonar_manager.create_quality_gate()
        sonar_manager.create_projects()
        group = gitlab_manager.create_environment()
        
        # Summary
        print_summary()
        
        print(f"\n🌐 GitLab projects: {group.web_url}")
        print(f"📊 SonarQube: {sonar_url}/projects")
        
    except Exception as e:
        error(f"Setup failed: {e}")