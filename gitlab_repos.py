#!/usr/bin/env python3
"""
Enhanced CI/CD Demo Environment Setup Script
Creates GitLab projects with comprehensive failure scenarios:
- 2 projects with SonarQube quality gate failures (including complex multi-iteration)
- 3 projects with different pipeline failures
- Progressive issue discovery for realistic testing
- GitLab projects are configured without webhooks (manual webhook setup required)
- SonarQube webhooks remain enabled for quality gate integration
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
AGENT_WEBHOOK_URL = "http://webhook-handler:8090/webhooks"

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
    "complex-banking-service": [
        {'key': 'SONAR_PROJECT_KEY', 'value': 'complex-banking-service'},
        {'key': 'JAVA_VERSION', 'value': '11'},
        {'key': 'MAVEN_OPTS', 'value': '-Dmaven.repo.local=$CI_PROJECT_DIR/.m2/repository'},
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
    },

    # 5. Complex Multi-Iteration Java Project with Layered Quality Issues
    "complex-banking-service": {
        "description": "Complex banking service with layered security and quality issues requiring multiple iterations",
        "language": "java",
        "files": {
            "src/main/java/com/bank/service/BankingService.java": """
package com.bank.service;

import java.sql.*;
import java.util.*;
import java.security.MessageDigest;
import java.io.File;
import java.io.FileWriter;
import java.math.BigDecimal;

/**
 * Banking Service with multiple layered issues that will be revealed progressively
 * This creates a scenario where fixing one issue reveals more issues underneath
 */
public class BankingService {
    
    // ITERATION 1 ISSUES: Critical Security Vulnerabilities
    private static final String DB_PASSWORD = "admin123"; // Hardcoded password - CRITICAL
    private static final String API_KEY = "sk-1234567890abcdef"; // Hardcoded API key - CRITICAL
    private static String adminPassword = "root"; // Another hardcoded secret
    
    private Connection dbConnection;
    private Map<String, String> userCache = new HashMap<>();
    
    // ITERATION 2 ISSUES: SQL Injection & Resource Leaks (revealed after fixing hardcoded secrets)
    public Account getAccount(String accountNumber) throws SQLException {
        // SQL Injection vulnerability - will be found after first iteration
        String query = "SELECT * FROM accounts WHERE account_number = '" + accountNumber + "'";
        Statement stmt = dbConnection.createStatement(); // Resource leak - not closed
        ResultSet rs = stmt.executeQuery(query); // Resource leak - not closed
        
        if (rs.next()) {
            Account account = new Account();
            account.setAccountNumber(rs.getString("account_number"));
            account.setBalance(rs.getBigDecimal("balance"));
            account.setCustomerId(rs.getString("customer_id"));
            return account;
        }
        return null;
        // Resources never closed - memory leak
    }
    
    // ITERATION 3 ISSUES: More Security Issues & Code Smells (revealed after fixing SQL injection)
    public boolean authenticateUser(String username, String password) {
        try {
            // Weak cryptography - MD5 is broken
            MessageDigest md = MessageDigest.getInstance("MD5");
            byte[] hashedPassword = md.digest(password.getBytes());
            
            // Convert to hex string
            StringBuilder sb = new StringBuilder();
            for (byte b : hashedPassword) {
                sb.append(String.format("%02x", b));
            }
            String hashedHex = sb.toString();
            
            // Cache credentials in plain text - security issue
            userCache.put(username, password); // Storing plain text password!
            
            return verifyPassword(hashedHex);
        } catch (Exception e) {
            // Empty catch block - code smell
            return false;
        }
    }
    
    // ITERATION 4 ISSUES: Code Duplication & Complex Methods (revealed after fixing crypto)
    public BigDecimal calculateInterest(String accountType, BigDecimal balance, int months) {
        // Complex method with duplicate logic
        if (accountType.equals("SAVINGS")) {
            if (balance.compareTo(new BigDecimal("1000")) > 0) {
                if (months > 12) {
                    return balance.multiply(new BigDecimal("0.025")).multiply(new BigDecimal(months)).divide(new BigDecimal("12"));
                } else {
                    return balance.multiply(new BigDecimal("0.02")).multiply(new BigDecimal(months)).divide(new BigDecimal("12"));
                }
            } else {
                if (months > 12) {
                    return balance.multiply(new BigDecimal("0.015")).multiply(new BigDecimal(months)).divide(new BigDecimal("12"));
                } else {
                    return balance.multiply(new BigDecimal("0.01")).multiply(new BigDecimal(months)).divide(new BigDecimal("12"));
                }
            }
        } else if (accountType.equals("CHECKING")) {
            if (balance.compareTo(new BigDecimal("1000")) > 0) {
                if (months > 12) {
                    return balance.multiply(new BigDecimal("0.015")).multiply(new BigDecimal(months)).divide(new BigDecimal("12"));
                } else {
                    return balance.multiply(new BigDecimal("0.01")).multiply(new BigDecimal(months)).divide(new BigDecimal("12"));
                }
            } else {
                if (months > 12) {
                    return balance.multiply(new BigDecimal("0.01")).multiply(new BigDecimal(months)).divide(new BigDecimal("12"));
                } else {
                    return balance.multiply(new BigDecimal("0.005")).multiply(new BigDecimal(months)).divide(new BigDecimal("12"));
                }
            }
        }
        return BigDecimal.ZERO;
    }
    
    // Duplicate method - code smell that will be found in later iterations
    public BigDecimal calculateLoanInterest(String loanType, BigDecimal principal, int months) {
        // Almost identical logic to calculateInterest - code duplication
        if (loanType.equals("PERSONAL")) {
            if (principal.compareTo(new BigDecimal("1000")) > 0) {
                if (months > 12) {
                    return principal.multiply(new BigDecimal("0.08")).multiply(new BigDecimal(months)).divide(new BigDecimal("12"));
                } else {
                    return principal.multiply(new BigDecimal("0.075")).multiply(new BigDecimal(months)).divide(new BigDecimal("12"));
                }
            } else {
                if (months > 12) {
                    return principal.multiply(new BigDecimal("0.075")).multiply(new BigDecimal(months)).divide(new BigDecimal("12"));
                } else {
                    return principal.multiply(new BigDecimal("0.07")).multiply(new BigDecimal(months)).divide(new BigDecimal("12"));
                }
            }
        } else if (loanType.equals("MORTGAGE")) {
            if (principal.compareTo(new BigDecimal("1000")) > 0) {
                if (months > 12) {
                    return principal.multiply(new BigDecimal("0.045")).multiply(new BigDecimal(months)).divide(new BigDecimal("12"));
                } else {
                    return principal.multiply(new BigDecimal("0.04")).multiply(new BigDecimal(months)).divide(new BigDecimal("12"));
                }
            } else {
                if (months > 12) {
                    return principal.multiply(new BigDecimal("0.04")).multiply(new BigDecimal(months)).divide(new BigDecimal("12"));
                } else {
                    return principal.multiply(new BigDecimal("0.035")).multiply(new BigDecimal(months)).divide(new BigDecimal("12"));
                }
            }
        }
        return BigDecimal.ZERO;
    }
    
    // ITERATION 5 ISSUES: File Security & Path Traversal (revealed after fixing duplication)
    public void exportAccountData(String accountNumber, String fileName) {
        try {
            // Path traversal vulnerability - fileName not validated
            File exportFile = new File("/tmp/exports/" + fileName);
            FileWriter writer = new FileWriter(exportFile); // Resource not closed
            
            // Export sensitive data without encryption
            writer.write("Account: " + accountNumber + "\\n");
            writer.write("Password: " + adminPassword + "\\n"); // Exposing secrets in files
            writer.write("API Key: " + API_KEY + "\\n");
            
            // File permissions not set - security issue
            
        } catch (Exception e) {
            // Another empty catch block
        }
    }
    
    // Helper method with its own issues
    private boolean verifyPassword(String hashedPassword) {
        // Weak comparison - timing attack vulnerability
        return hashedPassword.equals("5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8");
    }
    
    // Constructor with issues
    public BankingService() {
        try {
            // Hardcoded connection string with embedded credentials
            String connectionString = "jdbc:postgresql://localhost:5432/bank?user=admin&password=" + DB_PASSWORD;
            this.dbConnection = DriverManager.getConnection(connectionString);
        } catch (SQLException e) {
            // Swallowing exceptions - bad practice
        }
    }
}
""",
            "src/main/java/com/bank/model/Account.java": """
package com.bank.model;

import java.math.BigDecimal;
import java.util.Date;

// Simple model class that will also get issues in later iterations
public class Account {
    private String accountNumber;
    private BigDecimal balance;
    private String customerId;
    private String accountType;
    private Date createdDate;
    
    // Missing proper validation in setters - will be flagged later
    public void setAccountNumber(String accountNumber) {
        this.accountNumber = accountNumber; // No validation
    }
    
    public void setBalance(BigDecimal balance) {
        this.balance = balance; // No validation for negative balances
    }
    
    public void setCustomerId(String customerId) {
        this.customerId = customerId; // No validation
    }
    
    // Getters
    public String getAccountNumber() { return accountNumber; }
    public BigDecimal getBalance() { return balance; }
    public String getCustomerId() { return customerId; }
    public String getAccountType() { return accountType; }
    public Date getCreatedDate() { return createdDate; }
    
    public void setAccountType(String accountType) { this.accountType = accountType; }
    public void setCreatedDate(Date createdDate) { this.createdDate = createdDate; }
}
""",
            "src/test/java/com/bank/service/BankingServiceTest.java": """
package com.bank.service;

import org.junit.Test;
import org.junit.Before;
import static org.junit.Assert.*;
import java.math.BigDecimal;

public class BankingServiceTest {
    private BankingService service;
    
    @Before
    public void setUp() {
        service = new BankingService();
    }
    
    @Test
    public void testCalculateInterest() {
        BigDecimal interest = service.calculateInterest("SAVINGS", new BigDecimal("1000"), 12);
        assertNotNull(interest);
        assertTrue(interest.compareTo(BigDecimal.ZERO) >= 0);
    }
    
    @Test
    public void testAuthenticateUser() {
        // This test will pass initially but reveal security issues
        boolean result = service.authenticateUser("testuser", "password123");
        // Test doesn't validate security properly
    }
    
    // Missing tests for edge cases and security scenarios
    // This will be flagged as insufficient test coverage in later iterations
}
""",
            "pom.xml": """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 
         https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    
    <groupId>com.bank</groupId>
    <artifactId>complex-banking-service</artifactId>
    <version>1.0.0</version>
    
    <properties>
        <maven.compiler.source>11</maven.compiler.source>
        <maven.compiler.target>11</maven.compiler.target>
        <sonar.coverage.exclusions>**/*Test.java</sonar.coverage.exclusions>
    </properties>
    
    <dependencies>
        <dependency>
            <groupId>org.postgresql</groupId>
            <artifactId>postgresql</artifactId>
            <version>42.5.1</version>
        </dependency>
        <dependency>
            <groupId>junit</groupId>
            <artifactId>junit</artifactId>
            <version>4.13.2</version>
            <scope>test</scope>
        </dependency>
    </dependencies>
    
    <build>
        <plugins>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-surefire-plugin</artifactId>
                <version>3.0.0-M7</version>
            </plugin>
        </plugins>
    </build>
</project>
""",
            "sonar-project.properties": """
# SonarQube project configuration for progressive issue discovery
sonar.projectKey=complex-banking-service
sonar.projectName=Complex Banking Service
sonar.projectVersion=1.0.0

# Source configuration
sonar.sources=src/main/java
sonar.tests=src/test/java
sonar.java.binaries=target/classes
sonar.java.test.binaries=target/test-classes

# Coverage settings to ensure security issues are caught
sonar.coverage.exclusions=**/*Test.java
sonar.cpd.java.minimumtokens=50

# Enable security rules
sonar.java.libraries=target/dependency/*.jar
""",
            ".gitlab-ci.yml": """
include:
  - project: 'cicd-demo/shared-pipeline'
    ref: main
    file: '/shared-template.yml'

variables:
  MAVEN_OPTS: "-Dmaven.repo.local=$CI_PROJECT_DIR/.m2/repository"

cache:
  paths:
    - .m2/repository/

build:
  extends: .java-build
  script:
    - mvn clean compile
  artifacts:
    paths:
      - target/
    expire_in: 1 hour

test:
  extends: .java-test
  needs: ["build"]
  script:
    - mvn test
  artifacts:
    reports:
      junit:
        - target/surefire-reports/TEST-*.xml

# Enhanced SonarQube analysis that will progressively find more issues
sonarqube-check:
  extends: .sonarqube-check
  needs: ["test"]
  script:
    - mvn sonar:sonar 
      -Dsonar.projectKey=complex-banking-service
      -Dsonar.host.url=$SONAR_HOST_URL 
      -Dsonar.login=$SONAR_TOKEN
      -Dsonar.qualitygate.wait=true
      -Dsonar.sources=src/main/java
      -Dsonar.tests=src/test/java
      -Dsonar.java.binaries=target/classes
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
            
            # Note: Webhook creation skipped for GitLab projects
            # Projects will be configured without webhooks
            info(f"  Project {project_name} configured (webhook creation skipped)")
            
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
        """Create SonarQube projects for quality analysis"""
        quality_projects = ["quality-demo", "complex-banking-service"]
        
        for project_key in quality_projects:
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
            
            info(f"  ✓ Created SonarQube project: {project_key}")
        
        success("All SonarQube projects created")

def print_summary():
    """Print summary of created projects"""
    print("\n" + "="*80)
    success("Demo environment created successfully!")
    
    print("\n📦 PROJECTS CREATED:")
    
    print("\n🚨 SONARQUBE QUALITY GATE FAILURES:")
    print("  • quality-demo: Java project with security issues and code smells")
    print("    - SQL injection vulnerability")
    print("    - Hardcoded password")
    print("    - Resource leak")
    print("    - Duplicate code")
    
    print("\n🔥 COMPLEX MULTI-ITERATION PROJECT:")
    print("  • complex-banking-service: Banking service with layered security issues")
    print("    � ITERATION 1: Critical security (hardcoded secrets)")
    print("    🔄 ITERATION 2: SQL injection & resource leaks")
    print("    🔄 ITERATION 3: Weak cryptography & credential caching")
    print("    🔄 ITERATION 4: Code duplication & complex methods")
    print("    🔄 ITERATION 5: File security & path traversal")
    print("    📈 Progressively reveals new issues as previous ones are fixed")
    
    print("\n�🔴 PIPELINE FAILURES:")
    print("  • python-api: Runtime error (division by zero in tests)")
    print("  • java-service: Compilation error (missing DatabaseHelper class)")
    print("  • node-app: Syntax error (missing closing bracket)")
    
    print("\n✅ KEY FEATURES:")
    print("  • Multi-iteration quality gate failures")
    print("  • Progressive issue discovery")
    print("  • Real-world security vulnerabilities")
    print("  • Different failure types (runtime, compile, syntax)")
    print("  • Two SonarQube projects for comprehensive demo")
    print("  • GitLab projects configured without webhooks")
    print("  • SonarQube webhooks enabled for quality gate integration")
    
    print("\n🎯 DEMO SCENARIOS:")
    print("  1. Simple fixes: Use python-api, java-service, node-app")
    print("  2. Quality analysis: Use quality-demo for straightforward SonarQube issues")
    print("  3. Complex iterations: Use complex-banking-service for multi-iteration fixes")
    
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
    print(f"- 5 projects (2 quality w/ multi-iteration, 3 pipeline failures)")
    print(f"- Enhanced quality gate for SonarQube")
    print(f"- SonarQube webhook integrations only")
    print(f"- Progressive issue discovery scenario")
    print(f"- GitLab projects without webhooks (manual setup required)")
    
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
        print(f"\n📝 NOTE: GitLab projects created without webhooks.")
        print(f"   If webhook integration is needed, manually configure webhooks in GitLab projects")
        print(f"   pointing to: {AGENT_WEBHOOK_URL}/gitlab")
        
    except Exception as e:
        error(f"Setup failed: {e}")