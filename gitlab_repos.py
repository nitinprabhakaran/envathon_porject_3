#!/usr/bin/env python3
"""
Enhanced CI/CD Demo Environment Setup Script
Creates GitLab projects with various failure scenarios including:
- SonarQube quality gate failures (bugs, vulnerabilities, code smells)
- Pipeline failures at different stages (build, test, package, docker)
- Similar error patterns for vector DB demonstration
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
QUALITY_GATE_NAME = "strict-quality-gate"
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
    {'key': 'CI_REGISTRY', 'value': 'localhost:5000'},
    {'key': 'DOCKER_HOST', 'value': 'tcp://docker:2375'},
    
    # SonarQube
    {'key': 'SONAR_HOST_URL', 'value': 'http://sonarqube:9000'},
    {'key': 'SONAR_TOKEN', 'value': 'sonar_token_placeholder', 'masked': True},
    
    # Language Versions (defaults)
    {'key': 'JAVA_VERSION', 'value': '11'},
    {'key': 'PYTHON_VERSION', 'value': '3.9'},
    {'key': 'NODE_VERSION', 'value': '16'},
    
    # Common settings
    {'key': 'GIT_DEPTH', 'value': '0'},
    {'key': 'FF_USE_FASTZIP', 'value': 'true'},
    {'key': 'ARTIFACT_COMPRESSION_LEVEL', 'value': 'fast'},
]

# Project-specific variables
PROJECT_VARIABLES = {
    "payment-service": [
        {'key': 'SERVICE_NAME', 'value': 'payment-service'},
        {'key': 'JAVA_VERSION', 'value': '11'},
        {'key': 'SONAR_PROJECT_KEY', 'value': 'payment-service'},
    ],
    "auth-api": [
        {'key': 'SERVICE_NAME', 'value': 'auth-api'},
        {'key': 'PYTHON_VERSION', 'value': '3.9'},
        {'key': 'SONAR_PROJECT_KEY', 'value': 'auth-api'},
    ],
    "notification-service": [
        {'key': 'SERVICE_NAME', 'value': 'notification-service'},
        {'key': 'NODE_VERSION', 'value': '16'},
        {'key': 'SONAR_PROJECT_KEY', 'value': 'notification-service'},
    ],
    "order-service": [
        {'key': 'SERVICE_NAME', 'value': 'order-service'},
        {'key': 'PYTHON_VERSION', 'value': '3.9'},
        {'key': 'SONAR_PROJECT_KEY', 'value': 'order-service'},
    ],
    "inventory-api": [
        {'key': 'SERVICE_NAME', 'value': 'inventory-api'},
        {'key': 'JAVA_VERSION', 'value': '11'},
        {'key': 'SONAR_PROJECT_KEY', 'value': 'inventory-api'},
    ],
    "report-generator": [
        {'key': 'SERVICE_NAME', 'value': 'report-generator'},
        {'key': 'NODE_VERSION', 'value': '16'},
        {'key': 'SONAR_PROJECT_KEY', 'value': 'report-generator'},
    ],
    "shipping-service": [
        {'key': 'SERVICE_NAME', 'value': 'shipping-service'},
        {'key': 'PYTHON_VERSION', 'value': '3.9'},
        {'key': 'SONAR_PROJECT_KEY', 'value': 'shipping-service'},
    ],
}

# Shared CI/CD templates
SHARED_TEMPLATES = {
    "templates/base.yml": """
# Base template with common configurations
variables:
  DOCKER_DRIVER: overlay2
  DOCKER_TLS_CERTDIR: ""
  SONAR_USER_HOME: "${CI_PROJECT_DIR}/.sonar"
  GIT_DEPTH: "0"

# Base job templates
.base-rules:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'

.docker-base:
  image: docker:24
  services:
    - docker:24-dind
  before_script:
    - docker info

# Cache templates
.maven-cache:
  cache:
    key: "${CI_JOB_NAME}"
    paths:
      - .m2/repository

.npm-cache:
  cache:
    key: "${CI_JOB_NAME}"
    paths:
      - node_modules/
      - .npm/

.pip-cache:
  cache:
    key: "${CI_JOB_NAME}"
    paths:
      - .cache/pip
      - venv/
""",

    "templates/java-maven.yml": """
include:
  - local: '/templates/base.yml'

stages:
  - build
  - test
  - quality
  - package
  - deploy

# Build stage
build:
  stage: build
  image: maven:3.8-openjdk-11
  extends: 
    - .base-rules
    - .maven-cache
  script:
    - mvn clean compile
  artifacts:
    paths:
      - target/
    expire_in: 1 hour

# Test stage
test:
  stage: test
  image: maven:3.8-openjdk-11
  extends: 
    - .base-rules
    - .maven-cache
  needs: ["build"]
  script:
    - mvn test
  artifacts:
    reports:
      junit:
        - target/surefire-reports/TEST-*.xml
    paths:
      - target/
    expire_in: 1 hour

# SonarQube analysis
sonarqube-check:
  stage: quality
  image: maven:3.8-openjdk-11
  extends: 
    - .base-rules
    - .maven-cache
  needs: ["test"]
  script:
    - mvn sonar:sonar 
      -Dsonar.projectKey=${SONAR_PROJECT_KEY:-$CI_PROJECT_NAME}
      -Dsonar.host.url=$SONAR_HOST_URL 
      -Dsonar.login=$SONAR_TOKEN 
      -Dsonar.qualitygate.wait=true
  allow_failure: false

# Package application
package:
  stage: package
  image: maven:3.8-openjdk-11
  extends: 
    - .base-rules
    - .maven-cache
  needs: ["test"]
  script:
    - mvn package -DskipTests
  artifacts:
    paths:
      - target/*.jar
    expire_in: 1 day

# Build Docker image
docker-build:
  stage: deploy
  extends: 
    - .docker-base
    - .base-rules
  needs: ["package"]
  script:
    - docker build -t ${SERVICE_NAME:-$CI_PROJECT_NAME}:$CI_COMMIT_SHORT_SHA .
    - echo "Docker image built successfully"
""",

    "templates/python.yml": r"""
include:
  - local: '/templates/base.yml'

stages:
  - build
  - test
  - quality
  - package
  - deploy

# Build dependencies
build:
  stage: build
  image: python:3.9
  extends: 
    - .base-rules
    - .pip-cache
  script:
    - python -m venv venv
    - source venv/bin/activate
    - pip install --upgrade pip
    - pip install -r requirements.txt
    - python -m py_compile *.py || true
  artifacts:
    paths:
      - venv/
    expire_in: 1 hour

# Run tests
test:
  stage: test
  image: python:3.9
  extends: 
    - .base-rules
    - .pip-cache
  needs: ["build"]
  script:
    - source venv/bin/activate
    - pip install pytest pytest-cov
    - pytest --junitxml=report.xml --cov=. --cov-report=xml --cov-report=term || true
  coverage: '/TOTAL.*\s+(\d+%)$/'
  artifacts:
    reports:
      junit: report.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
    expire_in: 1 hour

# Code quality checks
lint:
  stage: quality
  image: python:3.9
  extends: .base-rules
  needs: ["build"]
  script:
    - source venv/bin/activate
    - pip install flake8 bandit
    - flake8 . --max-line-length=100 --exclude=venv || true
    - bandit -r . -f json -o bandit-report.json || true
  artifacts:
    reports:
      sast: bandit-report.json
  allow_failure: true

# SonarQube analysis
sonarqube-check:
  stage: quality
  image: sonarsource/sonar-scanner-cli:latest
  extends: .base-rules
  needs: ["test"]
  script:
    - sonar-scanner 
      -Dsonar.projectKey=${SONAR_PROJECT_KEY:-$CI_PROJECT_NAME}
      -Dsonar.sources=${SONAR_SOURCES:-.}
      -Dsonar.host.url=$SONAR_HOST_URL 
      -Dsonar.login=$SONAR_TOKEN 
      -Dsonar.python.coverage.reportPaths=coverage.xml
      -Dsonar.qualitygate.wait=true
  allow_failure: false

# Package application
package:
  stage: package
  image: python:3.9
  extends: .base-rules
  needs: ["test"]
  script:
    - python setup.py sdist bdist_wheel || echo "No setup.py found"
  artifacts:
    paths:
      - dist/
    expire_in: 1 day

# Build Docker image
docker-build:
  stage: deploy
  extends: 
    - .docker-base
    - .base-rules
  script:
    - docker build -t ${SERVICE_NAME:-$CI_PROJECT_NAME}:$CI_COMMIT_SHORT_SHA .
    - echo "Docker image built successfully"
""",

    "templates/nodejs.yml": r"""
include:
  - local: '/templates/base.yml'

stages:
  - build
  - test
  - quality
  - package
  - deploy

# Install dependencies
build:
  stage: build
  image: node:16
  extends: 
    - .base-rules
    - .npm-cache
  script:
    - npm ci || npm install
  artifacts:
    paths:
      - node_modules/
    expire_in: 1 hour

# Run tests
test:
  stage: test
  image: node:16
  extends: 
    - .base-rules
    - .npm-cache
  needs: ["build"]
  script:
    - npm test -- --watchAll=false --coverage --coverageReporters=cobertura || true
  coverage: '/Lines\s*:\s*(\d+\.?\d*)%/'
  artifacts:
    reports:
      junit: junit.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage/cobertura-coverage.xml
    paths:
      - coverage/
    expire_in: 1 hour

# Lint code
lint:
  stage: quality
  image: node:16
  extends: .base-rules
  needs: ["build"]
  script:
    - npm run lint || true
  allow_failure: true

# SonarQube analysis
sonarqube-check:
  stage: quality
  image: sonarsource/sonar-scanner-cli:latest
  extends: .base-rules
  needs: ["test"]
  script:
    - sonar-scanner 
      -Dsonar.projectKey=${SONAR_PROJECT_KEY:-$CI_PROJECT_NAME}
      -Dsonar.sources=${SONAR_SOURCES:-.}
      -Dsonar.host.url=$SONAR_HOST_URL 
      -Dsonar.login=$SONAR_TOKEN 
      -Dsonar.javascript.lcov.reportPaths=coverage/lcov.info
      -Dsonar.qualitygate.wait=true
  allow_failure: false

# Package application
package:
  stage: package
  image: node:16
  extends: .base-rules
  needs: ["test"]
  script:
    - npm run build || echo "No build script found"
    - npm pack
  artifacts:
    paths:
      - "*.tgz"
      - dist/
      - build/
    expire_in: 1 day

# Build Docker image
docker-build:
  stage: deploy
  extends: 
    - .docker-base
    - .base-rules
  script:
    - docker build -t ${SERVICE_NAME:-$CI_PROJECT_NAME}:$CI_COMMIT_SHORT_SHA .
    - echo "Docker image built successfully"
"""
}

# Project definitions
PROJECTS = {
    # 1. Java - Payment Service (MANY SonarQube issues)
    "payment-service": {
        "description": "Payment service with extensive SonarQube issues",
        "language": "java",
        "template": "java-maven.yml",
        "files": {
            "src/main/java/com/demo/payment/PaymentService.java": """
package com.demo.payment;

import java.sql.*;
import java.util.Random;
import java.io.*;
import javax.crypto.Cipher;
import javax.crypto.spec.SecretKeySpec;

public class PaymentService {
    private static final String PASSWORD = "admin123"; // Security vulnerability: hardcoded password
    private static final String DB_PASSWORD = "password"; // Another hardcoded password
    private Connection conn; // Bug: Connection never closed
    
    // Bug: SQL Injection vulnerability
    public boolean processPayment(String userId, double amount) throws SQLException {
        String query = "SELECT balance FROM users WHERE id = '" + userId + "'";
        conn = DriverManager.getConnection("jdbc:h2:mem:test", "sa", PASSWORD);
        Statement stmt = conn.createStatement();
        ResultSet rs = stmt.executeQuery(query);
        
        // Bug: Resources not closed (memory leak)
        if (rs.next()) {
            double balance = rs.getDouble("balance");
            if (balance >= amount) {
                // Code smell: Empty if statement
                if (amount > 1000) {
                    // TODO: Add fraud check
                }
                
                // Bug: SQL injection in update
                String updateQuery = "UPDATE users SET balance = balance - " + amount + " WHERE id = '" + userId + "'";
                stmt.executeUpdate(updateQuery);
                
                return true;
            }
        }
        return false;
    }
    
    // Security vulnerability: Weak encryption
    public String encryptCardNumber(String cardNumber) throws Exception {
        String key = "1234567890123456"; // Hardcoded encryption key
        SecretKeySpec spec = new SecretKeySpec(key.getBytes(), "AES");
        Cipher cipher = Cipher.getInstance("AES");
        cipher.init(Cipher.ENCRYPT_MODE, spec);
        return new String(cipher.doFinal(cardNumber.getBytes()));
    }
    
    // Code smell: Duplicate code
    public double calculateFee(double amount) {
        if (amount < 100) {
            return amount * 0.02;
        } else if (amount < 1000) {
            return amount * 0.015;
        } else {
            return amount * 0.01;
        }
    }
    
    public double calculateTax(double amount) {
        if (amount < 100) {
            return amount * 0.02;
        } else if (amount < 1000) {
            return amount * 0.015;
        } else {
            return amount * 0.01;
        }
    }
    
    public double calculateDiscount(double amount) {
        if (amount < 100) {
            return amount * 0.02;
        } else if (amount < 1000) {
            return amount * 0.015;
        } else {
            return amount * 0.01;
        }
    }
    
    // Security: Weak random number generator
    public String generateTransactionId() {
        Random rand = new Random(); // Should use SecureRandom
        return "TXN" + rand.nextInt(10000);
    }
    
    // Bug: Path traversal vulnerability
    public void saveReceipt(String filename, String content) throws IOException {
        File file = new File("/receipts/" + filename); // No validation
        FileWriter writer = new FileWriter(file);
        writer.write(content);
        // Bug: Writer not closed
    }
    
    // Code smell: God method (too complex)
    public void processRefund(String transactionId, double amount, String reason, 
                            String userId, String merchantId, boolean partial) {
        // 100+ lines of complex logic here...
        if (transactionId != null) {
            if (amount > 0) {
                if (reason != null && !reason.isEmpty()) {
                    if (userId != null) {
                        if (merchantId != null) {
                            if (partial) {
                                // Process partial refund
                            } else {
                                // Process full refund
                            }
                        }
                    }
                }
            }
        }
    }
    
    // Unused method (code smell)
    private void oldMethod() {
        System.out.println("This method is never used");
    }
    
    private void anotherUnusedMethod() {
        System.out.println("Another unused method");
    }
    
    // Bug: Synchronization issues
    private int counter = 0;
    public void incrementCounter() {
        counter++; // Not thread-safe
    }
}
""",
            "src/main/java/com/demo/payment/CreditCardValidator.java": """
package com.demo.payment;

import java.util.regex.Pattern;

public class CreditCardValidator {
    
    // Bug: Null pointer potential
    public boolean validateCard(String cardNumber) {
        if (cardNumber.length() != 16) { // NPE if cardNumber is null
            return false;
        }
        
        // Security: Logging sensitive data
        System.out.println("Validating card: " + cardNumber);
        
        // Code smell: Complex condition
        if (cardNumber.startsWith("4") || cardNumber.startsWith("5") || 
            cardNumber.startsWith("37") || cardNumber.startsWith("6") ||
            cardNumber.startsWith("35") || cardNumber.startsWith("34") ||
            cardNumber.startsWith("30") || cardNumber.startsWith("36")) {
            return true;
        }
        
        return false;
    }
    
    // Bug: Array index out of bounds potential
    public String getMaskedNumber(String cardNumber) {
        char[] masked = new char[16];
        for (int i = 0; i < 16; i++) {
            masked[i] = cardNumber.charAt(i); // Crash if cardNumber is shorter
        }
        return new String(masked);
    }
    
    // Security: Regex DoS vulnerability
    public boolean validateWithRegex(String input) {
        // Catastrophic backtracking vulnerability
        Pattern pattern = Pattern.compile("(a+)+b");
        return pattern.matcher(input).matches();
    }
    
    // Code smell: Dead code
    public void deadMethod() {
        int x = 1;
        if (x > 2) {
            System.out.println("This will never execute");
        }
    }
}
""",
            "src/main/java/com/demo/payment/DatabaseHelper.java": """
package com.demo.payment;

import java.sql.*;

public class DatabaseHelper {
    
    // Security: Connection string with password
    private static final String URL = "jdbc:mysql://localhost:3306/payments?user=root&password=root123";
    
    // Bug: Connection leak
    public ResultSet executeQuery(String query) throws SQLException {
        Connection conn = DriverManager.getConnection(URL);
        Statement stmt = conn.createStatement();
        return stmt.executeQuery(query); // Connection never closed
    }
    
    // Security: SQL injection
    public void deleteUser(String userId) throws SQLException {
        String query = "DELETE FROM users WHERE id = " + userId;
        executeQuery(query);
    }
    
    // Code smell: Commented out code
    public void processData() {
        // Connection conn = getConnection();
        // Statement stmt = conn.createStatement();
        // ResultSet rs = stmt.executeQuery("SELECT * FROM payments");
        // while(rs.next()) {
        //     process(rs);
        // }
    }
}
""",
            "src/test/java/com/demo/payment/PaymentServiceTest.java": """
package com.demo.payment;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class PaymentServiceTest {
    
    @Test
    void testCalculateFee() {
        PaymentService service = new PaymentService();
        assertEquals(2.0, service.calculateFee(100));
    }
    
    @Test
    void testGenerateTransactionId() {
        PaymentService service = new PaymentService();
        assertNotNull(service.generateTransactionId());
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
    <artifactId>payment-service</artifactId>
    <version>1.0.0</version>
    
    <properties>
        <maven.compiler.source>11</maven.compiler.source>
        <maven.compiler.target>11</maven.compiler.target>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
        <sonar.organization>demo</sonar.organization>
        <sonar.projectKey>payment-service</sonar.projectKey>
    </properties>
    
    <dependencies>
        <dependency>
            <groupId>com.h2database</groupId>
            <artifactId>h2</artifactId>
            <version>2.1.214</version>
        </dependency>
        <dependency>
            <groupId>mysql</groupId>
            <artifactId>mysql-connector-java</artifactId>
            <version>8.0.33</version>
        </dependency>
        <dependency>
            <groupId>org.junit.jupiter</groupId>
            <artifactId>junit-jupiter</artifactId>
            <version>5.9.2</version>
            <scope>test</scope>
        </dependency>
    </dependencies>
    
    <build>
        <plugins>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-surefire-plugin</artifactId>
                <version>3.0.0-M9</version>
            </plugin>
        </plugins>
    </build>
</project>
""",
            "Dockerfile": """FROM openjdk:11-jre-slim
WORKDIR /app
COPY target/*.jar app.jar
EXPOSE 8080
CMD ["java", "-jar", "app.jar"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/java-maven.yml'
"""
        }
    },

    # 2. Python - Auth API (Build failure + quality issues)
    "auth-api": {
        "description": "Auth API with build failure and security issues",
        "language": "python",
        "template": "python.yml",
        "files": {
            "auth_service.py": """
import jwt  # Missing from requirements.txt
import hashlib
import pickle  # Security risk
import os
import subprocess
from datetime import datetime, timedelta

class AuthService:
    SECRET_KEY = "secret123"  # Security vulnerability: hardcoded secret
    API_KEY = "sk-1234567890abcdef"  # Another hardcoded credential
    
    def __init__(self):
        self.users = {}  # In-memory storage (not thread-safe)
        self.sessions = []  # Memory leak: sessions never cleaned
    
    def create_token(self, user_id):
        payload = {
            'user_id': user_id,
            'exp': datetime.utcnow() + timedelta(hours=1)
        }
        return jwt.encode(payload, self.SECRET_KEY, algorithm='HS256')
    
    def verify_token(self, token):
        try:
            payload = jwt.decode(token, self.SECRET_KEY, algorithms=['HS256'])
            return payload['user_id']
        except:  # Bug: Bare except clause
            return None
    
    def hash_password(self, password):
        # Security: Weak hashing algorithm (MD5)
        return hashlib.md5(password.encode()).hexdigest()
    
    # Security: Command injection vulnerability
    def verify_email(self, email):
        cmd = f"echo {email} | grep -E '^[a-zA-Z0-9]+@[a-zA-Z0-9]+\\.[a-zA-Z]+$'"
        result = subprocess.shell(cmd, shell=True)  # Command injection
        return result.returncode == 0
    
    # Security: Insecure deserialization
    def load_user_data(self, data):
        return pickle.loads(data)  # Dangerous deserialization
    
    # Bug: SQL injection
    def get_user(self, user_id):
        query = f"SELECT * FROM users WHERE id = '{user_id}'"  # SQL injection
        # Simulate database query
        return query
    
    # Code smell: Duplicate code
    def is_admin(self, user_id):
        user = self.users.get(user_id)
        if user and user.get('role') == 'admin':
            return True
        return False
    
    def is_moderator(self, user_id):
        user = self.users.get(user_id)
        if user and user.get('role') == 'moderator':
            return True
        return False
    
    def is_user(self, user_id):
        user = self.users.get(user_id)
        if user and user.get('role') == 'user':
            return True
        return False
    
    # Security: Path traversal
    def save_profile_picture(self, user_id, filename):
        path = f"/uploads/{filename}"  # No validation
        with open(path, 'wb') as f:
            f.write(b"data")  # Simplified for demo
    
    # Code smell: Long method
    def authenticate_user(self, username, password, ip_address, user_agent, 
                         remember_me, two_factor_code, captcha_response):
        # Complex authentication logic...
        if username and password:
            if ip_address:
                if user_agent:
                    if captcha_response:
                        hashed = self.hash_password(password)
                        # More nested logic...
                        return True
        return False
    
    # Unused function
    def legacy_auth(self):
        pass
    
    # Bug: Resource leak
    def read_config(self):
        f = open('/etc/config.txt', 'r')  # File never closed
        return f.read()
""",
            "test_auth.py": """
import pytest
from auth_service import AuthService

def test_hash_password():
    service = AuthService()
    hashed = service.hash_password("test123")
    assert len(hashed) == 32

def test_create_token():
    service = AuthService()
    # This will fail because jwt is not installed
    token = service.create_token("user123")
    assert token is not None
""",
            "requirements.txt": """pytest==7.4.0
pytest-cov==4.1.0
# jwt is missing - will cause build failure
""",
            "config.py": """
# Security: Exposed credentials
DATABASE_URL = "postgresql://admin:password123@localhost/authdb"
REDIS_PASSWORD = "redis123"
AWS_SECRET_KEY = "aws-secret-key-here"

# Code smell: Magic numbers
MAX_LOGIN_ATTEMPTS = 3
SESSION_TIMEOUT = 3600
TOKEN_LENGTH = 32
""",
            "Dockerfile": """FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "auth_service.py"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/python.yml'
"""
        }
    },

    # 3. Node.js - Notification Service (Test failure + quality issues)
    "notification-service": {
        "description": "Notification service with failing tests and quality issues",
        "language": "javascript",
        "template": "nodejs.yml",
        "files": {
            "notification.js": """
const fs = require('fs');
const exec = require('child_process').exec;

// Security: Hardcoded API keys
const SENDGRID_API_KEY = 'SG.1234567890abcdef';
const TWILIO_AUTH_TOKEN = 'auth_token_here';
const DB_PASSWORD = 'password123';

class NotificationService {
    constructor() {
        this.notifications = [];
        this.connections = []; // Memory leak: connections never closed
    }
    
    sendEmail(to, subject, body) {
        // Bug: No input validation
        if (!to || !subject) {
            throw new Error('Missing required fields');
        }
        
        // Security: Command injection
        exec(`echo "${body}" | mail -s "${subject}" ${to}`);
        
        const notification = {
            id: Date.now(),
            type: 'email',
            to,
            subject,
            body,
            sent: new Date()
        };
        
        this.notifications.push(notification);
        
        // Security: Logging sensitive data
        console.log(`Sending email to ${to} with API key ${SENDGRID_API_KEY}`);
        
        return notification;
    }
    
    // Security: SQL injection
    getNotificationsByUser(userId) {
        const query = `SELECT * FROM notifications WHERE user_id = '${userId}'`;
        // Simulated query execution
        return this.notifications.filter(n => n.userId === userId);
    }
    
    getNotifications(type) {
        return this.notifications.filter(n => n.type === type);
    }
    
    // Bug: Returns wrong count (off-by-one error)
    getCount() {
        return this.notifications.length + 1;
    }
    
    // Security: Path traversal
    saveNotificationLog(filename) {
        const path = `/logs/${filename}`; // No sanitization
        fs.writeFileSync(path, JSON.stringify(this.notifications));
    }
    
    // Code smell: Duplicate code
    sendSMS(phone, message) {
        if (!phone || !message) {
            throw new Error('Missing required fields');
        }
        
        const notification = {
            id: Date.now(),
            type: 'sms',
            phone,
            message,
            sent: new Date()
        };
        
        this.notifications.push(notification);
        return notification;
    }
    
    sendPush(deviceId, title, message) {
        if (!deviceId || !title) {
            throw new Error('Missing required fields');
        }
        
        const notification = {
            id: Date.now(),
            type: 'push',
            deviceId,
            title,
            message,
            sent: new Date()
        };
        
        this.notifications.push(notification);
        return notification;
    }
    
    // Bug: Infinite loop potential
    retryFailedNotifications() {
        const failed = this.notifications.filter(n => n.failed);
        failed.forEach(n => {
            // Missing exit condition
            while (n.failed) {
                this.sendEmail(n.to, n.subject, n.body);
            }
        });
    }
    
    // Code smell: Dead code
    oldSendMethod() {
        // This method is never called
        console.log('Old method');
    }
    
    // Security: Eval usage
    executeTemplate(template, data) {
        return eval(template); // Security vulnerability
    }
}

// Bug: Global variable pollution
notificationCount = 0;

module.exports = NotificationService;
""",
            "notification.test.js": """
const NotificationService = require('./notification');

describe('NotificationService', () => {
    let service;
    
    beforeEach(() => {
        service = new NotificationService();
    });
    
    test('sends email notification', () => {
        const result = service.sendEmail('test@example.com', 'Test', 'Body');
        expect(result).toHaveProperty('id');
        expect(result.type).toBe('email');
    });
    
    test('throws error for missing fields', () => {
        expect(() => {
            service.sendEmail('test@example.com');
        }).toThrow('Missing required fields');
    });
    
    test('returns correct count', () => {
        service.sendEmail('test@example.com', 'Test', 'Body');
        // This test will fail due to off-by-one error
        expect(service.getCount()).toBe(1);
    });
});
""",
            "config.js": """
// Security: Exposed configuration
module.exports = {
    database: {
        host: 'localhost',
        user: 'root',
        password: 'root123', // Hardcoded password
        database: 'notifications'
    },
    redis: {
        host: 'localhost',
        password: 'redis123' // Another hardcoded password
    },
    api: {
        sendgrid: 'SG.actual_api_key_here',
        twilio: {
            accountSid: 'AC1234567890',
            authToken: 'auth_token_12345'
        }
    }
};
""",
            "package.json": """{
  "name": "notification-service",
  "version": "1.0.0",
  "description": "Notification service",
  "main": "notification.js",
  "scripts": {
    "test": "jest --watchAll=false",
    "lint": "eslint ."
  },
  "devDependencies": {
    "jest": "^29.5.0",
    "eslint": "^8.42.0"
  },
  "jest": {
    "testEnvironment": "node",
    "coverageDirectory": "coverage",
    "collectCoverageFrom": ["*.js", "!*.test.js"]
  }
}
""",
            ".eslintrc.json": """{
  "env": {
    "node": true,
    "es2021": true,
    "jest": true
  },
  "extends": "eslint:recommended",
  "rules": {
    "no-unused-vars": "error"
  }
}
""",
            "Dockerfile": """FROM node:16-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .
EXPOSE 3000
CMD ["node", "notification.js"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/nodejs.yml'
"""
        }
    },

    # 4. Python - Order Service (Package failure + quality issues)
    "order-service": {
        "description": "Order service with package failure and code issues",
        "language": "python",
        "template": "python.yml",
        "files": {
            "order_service.py": """
import os
import eval  # Security risk
import pickle
import random

# Security: Hardcoded secrets
API_TOKEN = "order-service-token-12345"
DATABASE_PASSWORD = "order_db_pass"

class OrderService:
    def __init__(self):
        self.orders = {}
        self.connections = []  # Memory leak
    
    def create_order(self, user_id, items):
        # Bug: Race condition with order ID generation
        order_id = len(self.orders) + 1
        
        # Security: Weak random for order confirmation
        confirmation_code = random.randint(1000, 9999)  # Should use secrets
        
        self.orders[order_id] = {
            'user_id': user_id,
            'items': items,
            'status': 'pending',
            'confirmation': confirmation_code
        }
        
        # Security: Logging sensitive data
        print(f"Order {order_id} created with confirmation {confirmation_code}")
        
        return order_id
    
    def get_order(self, order_id):
        return self.orders.get(order_id)
    
    # Security: SQL injection
    def get_user_orders(self, user_id):
        query = f"SELECT * FROM orders WHERE user_id = {user_id}"
        # Simulated query
        return [o for o in self.orders.values() if o['user_id'] == user_id]
    
    # Security: Command injection
    def export_order(self, order_id, format):
        os.system(f"./export.sh {order_id} {format}")  # Command injection
    
    # Security: Insecure deserialization
    def import_order(self, data):
        return pickle.loads(data)  # Dangerous
    
    # Code smell: Long method with complex logic
    def process_order(self, order_id, payment_method, shipping_address, 
                     billing_address, coupon_code, gift_wrap, express_shipping):
        order = self.orders.get(order_id)
        if order:
            if payment_method:
                if shipping_address:
                    if billing_address:
                        if coupon_code:
                            # Apply coupon
                            pass
                        if gift_wrap:
                            # Add gift wrap
                            pass
                        if express_shipping:
                            # Set express shipping
                            pass
                        # Process payment
                        # Update inventory
                        # Send confirmation
                        return True
        return False
    
    # Bug: File handle leak
    def save_order_receipt(self, order_id):
        f = open(f'/receipts/order_{order_id}.txt', 'w')
        f.write(str(self.orders.get(order_id)))
        # File not closed
    
    # Code smell: Duplicate validation logic
    def validate_item_availability(self, item_id):
        # Complex validation logic
        return True
    
    def validate_item_price(self, item_id):
        # Same complex validation logic
        return True
    
    def validate_item_shipping(self, item_id):
        # Same complex validation logic again
        return True
    
    # Unused method
    def legacy_process(self):
        pass
""",
            "test_order.py": """
import pytest
from order_service import OrderService

def test_create_order():
    service = OrderService()
    order_id = service.create_order('user123', ['item1', 'item2'])
    assert order_id == 1

def test_get_order():
    service = OrderService()
    order_id = service.create_order('user123', ['item1'])
    order = service.get_order(order_id)
    assert order['user_id'] == 'user123'
""",
            "requirements.txt": """pytest==7.4.0
pytest-cov==4.1.0
""",
            "setup.py": """
from setuptools import setup

# Intentional syntax error to cause package failure
setup(
    name='order-service'
    version='1.0.0',  # Missing comma above
    packages=['order_service']
)
""",
            "config.py": """
# Security: Exposed credentials
DATABASE_URL = "postgresql://orderuser:orderpass123@localhost/orders"
REDIS_URL = "redis://:redis_password@localhost:6379"
STRIPE_API_KEY = "sk_live_1234567890abcdef"
""",
            "Dockerfile": """FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "order_service.py"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/python.yml'
"""
        }
    },

    # 5. Java - Inventory API (Docker failure + quality issues)
    "inventory-api": {
        "description": "Inventory API with Docker build failure and quality issues",
        "language": "java",
        "template": "java-maven.yml",
        "files": {
            "src/main/java/com/demo/inventory/InventoryService.java": """
package com.demo.inventory;

import java.util.*;
import java.io.*;
import java.sql.*;

public class InventoryService {
    // Bug: Not thread-safe
    private Map<String, Integer> inventory = new HashMap<>();
    private static String DB_PASSWORD = "inventory123"; // Security: hardcoded
    
    // Bug: Race condition
    public void addItem(String itemId, int quantity) {
        inventory.put(itemId, inventory.getOrDefault(itemId, 0) + quantity);
    }
    
    public boolean checkAvailability(String itemId, int quantity) {
        return inventory.getOrDefault(itemId, 0) >= quantity;
    }
    
    // Bug: Race condition in concurrent environment
    public void removeItem(String itemId, int quantity) {
        int current = inventory.getOrDefault(itemId, 0);
        inventory.put(itemId, Math.max(0, current - quantity));
    }
    
    // Security: SQL injection
    public List<String> searchItems(String query) throws SQLException {
        String sql = "SELECT * FROM items WHERE name LIKE '%" + query + "%'";
        // Vulnerable to SQL injection
        return Arrays.asList(sql);
    }
    
    // Bug: Resource leak
    public void loadInventory(String filename) throws IOException {
        BufferedReader reader = new BufferedReader(new FileReader(filename));
        String line;
        while ((line = reader.readLine()) != null) {
            // Process line
        }
        // Reader not closed
    }
    
    // Code smell: Duplicate logic
    public double calculateStorageCost(String itemId) {
        Integer quantity = inventory.get(itemId);
        if (quantity == null) return 0;
        if (quantity < 100) return quantity * 0.5;
        if (quantity < 1000) return quantity * 0.3;
        return quantity * 0.2;
    }
    
    public double calculateHandlingCost(String itemId) {
        Integer quantity = inventory.get(itemId);
        if (quantity == null) return 0;
        if (quantity < 100) return quantity * 0.5;
        if (quantity < 1000) return quantity * 0.3;
        return quantity * 0.2;
    }
    
    // Security: Path traversal
    public void exportInventory(String path) throws IOException {
        File file = new File("/exports/" + path); // No validation
        FileWriter writer = new FileWriter(file);
        writer.write(inventory.toString());
        writer.close();
    }
    
    // Bug: Null pointer potential
    public String getItemDetails(String itemId) {
        return inventory.get(itemId).toString(); // NPE if item doesn't exist
    }
    
    // Code smell: God class - too many responsibilities
    public void processOrder(String orderId) { /* ... */ }
    public void updatePricing(String itemId) { /* ... */ }
    public void generateReport() { /* ... */ }
    public void syncWithSuppliers() { /* ... */ }
    public void handleReturns(String orderId) { /* ... */ }
}
""",
            "src/main/java/com/demo/inventory/DatabaseConfig.java": """
package com.demo.inventory;

public class DatabaseConfig {
    // Security: Hardcoded credentials
    public static final String URL = "jdbc:mysql://localhost:3306/inventory";
    public static final String USER = "root";
    public static final String PASSWORD = "root123";
    
    // Security: Weak encryption key
    public static final String ENCRYPTION_KEY = "1234567890123456";
}
""",
            "src/test/java/com/demo/inventory/InventoryServiceTest.java": """
package com.demo.inventory;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class InventoryServiceTest {
    
    @Test
    void testAddItem() {
        InventoryService service = new InventoryService();
        service.addItem("ITEM001", 10);
        assertTrue(service.checkAvailability("ITEM001", 5));
    }
    
    @Test
    void testRemoveItem() {
        InventoryService service = new InventoryService();
        service.addItem("ITEM002", 10);
        service.removeItem("ITEM002", 5);
        assertTrue(service.checkAvailability("ITEM002", 5));
        assertFalse(service.checkAvailability("ITEM002", 6));
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
    <artifactId>inventory-api</artifactId>
    <version>1.0.0</version>
    
    <properties>
        <maven.compiler.source>11</maven.compiler.source>
        <maven.compiler.target>11</maven.compiler.target>
    </properties>
    
    <dependencies>
        <dependency>
            <groupId>mysql</groupId>
            <artifactId>mysql-connector-java</artifactId>
            <version>8.0.33</version>
        </dependency>
        <dependency>
            <groupId>org.junit.jupiter</groupId>
            <artifactId>junit-jupiter</artifactId>
            <version>5.9.2</version>
            <scope>test</scope>
        </dependency>
    </dependencies>
    
    <build>
        <plugins>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-surefire-plugin</artifactId>
                <version>3.0.0-M9</version>
            </plugin>
        </plugins>
    </build>
</project>
""",
            "Dockerfile": """FROM openjdk:11-jre-slim
WORKDIR /app
# Wrong path - will cause Docker build to fail
COPY target/wrong-name.jar app.jar
EXPOSE 8080
CMD ["java", "-jar", "app.jar"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/java-maven.yml'
"""
        }
    },

    # 6. Node.js - Report Generator (Similar test failure + quality issues)
    "report-generator": {
        "description": "Report generator with similar test failure pattern and quality issues",
        "language": "javascript",
        "template": "nodejs.yml",
        "files": {
            "report.js": """
const fs = require('fs');
const { exec } = require('child_process');

// Security: Hardcoded credentials
const DB_CONNECTION = 'mongodb://admin:admin123@localhost:27017/reports';
const API_KEY = 'report-api-key-12345';

class ReportGenerator {
    constructor() {
        this.reports = [];
        this.templates = {}; // Memory leak: templates never cleared
    }
    
    generateReport(type, data) {
        // Bug: No input validation
        const report = {
            id: this.reports.length + 1,
            type,
            data,
            timestamp: new Date()
        };
        
        // Security: Command injection
        if (type === 'pdf') {
            exec(`wkhtmltopdf ${data.url} report.pdf`); // Dangerous
        }
        
        this.reports.push(report);
        
        // Security: Logging sensitive data
        console.log(`Generated report with data: ${JSON.stringify(data)}`);
        
        return report;
    }
    
    // Bug: Returns wrong count (similar to notification-service)
    getReportCount() {
        return this.reports.length + 1; // Off by one error
    }
    
    getReportsByType(type) {
        return this.reports.filter(r => r.type === type);
    }
    
    // Security: Path traversal
    saveReport(filename, content) {
        const path = `/reports/${filename}`; // No sanitization
        fs.writeFileSync(path, content);
    }
    
    // Security: Template injection
    renderTemplate(template, data) {
        // Vulnerable to template injection
        return eval('`' + template + '`');
    }
    
    // Code smell: Duplicate code (similar pattern)
    calculateReportSize(reportId) {
        const report = this.reports.find(r => r.id === reportId);
        if (!report) return 0;
        if (report.data.length < 100) return 1;
        if (report.data.length < 1000) return 2;
        return 3;
    }
    
    calculateReportComplexity(reportId) {
        const report = this.reports.find(r => r.id === reportId);
        if (!report) return 0;
        if (report.data.length < 100) return 1;
        if (report.data.length < 1000) return 2;
        return 3;
    }
    
    // Bug: Infinite recursion potential
    generateRecursiveReport(depth = 0) {
        if (depth > 10) return; // Weak termination condition
        return this.generateRecursiveReport(depth); // Bug: doesn't increment
    }
    
    // Security: SQL injection
    getReportsByUser(userId) {
        const query = `SELECT * FROM reports WHERE user_id = '${userId}'`;
        // Simulated vulnerable query
        return this.reports;
    }
    
    // Code smell: Dead code
    oldGenerateMethod() {
        // Never called
        console.log('Old method');
    }
}

// Bug: Global pollution
reportCount = 0;

module.exports = ReportGenerator;
""",
            "report.test.js": """
const ReportGenerator = require('./report');

describe('ReportGenerator', () => {
    let generator;
    
    beforeEach(() => {
        generator = new ReportGenerator();
    });
    
    test('generates report', () => {
        const report = generator.generateReport('monthly', {sales: 1000});
        expect(report).toHaveProperty('id', 1);
        expect(report.type).toBe('monthly');
    });
    
    test('returns correct report count', () => {
        generator.generateReport('monthly', {sales: 1000});
        // This test will fail - same pattern as notification-service
        expect(generator.getReportCount()).toBe(1);
    });
});
""",
            "config.js": """
// Security: Exposed secrets
module.exports = {
    mongodb: {
        url: 'mongodb://admin:password123@localhost:27017/reports',
        options: {
            user: 'admin',
            password: 'password123'
        }
    },
    aws: {
        accessKeyId: 'AKIAIOSFODNN7EXAMPLE',
        secretAccessKey: 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'
    }
};
""",
            "package.json": """{
  "name": "report-generator",
  "version": "1.0.0",
  "description": "Report generation service",
  "main": "report.js",
  "scripts": {
    "test": "jest --watchAll=false",
    "lint": "eslint ."
  },
  "devDependencies": {
    "jest": "^29.5.0",
    "eslint": "^8.42.0"
  },
  "jest": {
    "testEnvironment": "node",
    "coverageDirectory": "coverage",
    "collectCoverageFrom": ["*.js", "!*.test.js"]
  }
}
""",
            "Dockerfile": """FROM node:16-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .
EXPOSE 3000
CMD ["node", "report.js"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/nodejs.yml'
"""
        }
    },

    # 7. Python - Shipping Service (Similar build failure + quality issues)
    "shipping-service": {
        "description": "Shipping service with pattern similar to auth-api",
        "language": "python",
        "template": "python.yml",
        "files": {
            "shipping_service.py": """
import requests  # Missing from requirements.txt - similar to auth-api
import os
import subprocess
import yaml
from datetime import datetime

# Security: Hardcoded API credentials
API_KEY = "shipping123"
FEDEX_KEY = "fedex_api_key_12345"
UPS_KEY = "ups_api_key_67890"
DATABASE_URL = "postgresql://ship:ship123@localhost/shipping"

class ShippingService:
    def __init__(self):
        self.shipments = {}
        self.carriers = []  # Memory leak
    
    def calculate_shipping(self, weight, distance):
        base_rate = 5.0
        return base_rate + (weight * 0.5) + (distance * 0.1)
    
    def track_package(self, tracking_id):
        # Security: SQL injection
        query = f"SELECT * FROM packages WHERE tracking_id = '{tracking_id}'"
        
        return {
            'id': tracking_id,
            'status': 'in_transit',
            'location': 'Unknown'
        }
    
    def create_label(self, order_data):
        # Missing dependency will cause failure
        response = requests.post('https://api.shipping.com/labels', 
                               json=order_data,
                               headers={'Authorization': self.API_KEY})
        return response.json()
    
    # Security: Command injection
    def generate_barcode(self, tracking_number):
        cmd = f"barcode -o barcode.png {tracking_number}"
        subprocess.call(cmd, shell=True)  # Command injection
    
    # Security: Path traversal
    def save_shipping_label(self, filename, content):
        path = f"/labels/{filename}"  # No validation
        with open(path, 'wb') as f:
            f.write(content)
    
    # Bug: YAML parsing vulnerability
    def load_config(self, config_str):
        return yaml.load(config_str)  # Should use safe_load
    
    # Code smell: Complex nested conditions
    def calculate_delivery_time(self, origin, destination, service_type, weight, 
                               is_hazmat, is_fragile, is_oversized):
        if origin and destination:
            if service_type == 'express':
                if weight < 50:
                    if not is_hazmat:
                        if not is_fragile:
                            if not is_oversized:
                                return 1
                            else:
                                return 3
                        else:
                            return 2
                    else:
                        return 5
                else:
                    return 4
            else:
                return 7
        return 10
    
    # Code smell: Duplicate validation
    def validate_address(self, address):
        if not address.get('street'):
            return False
        if not address.get('city'):
            return False
        if not address.get('zip'):
            return False
        return True
    
    def validate_sender_address(self, address):
        if not address.get('street'):
            return False
        if not address.get('city'):
            return False
        if not address.get('zip'):
            return False
        return True
    
    def validate_receiver_address(self, address):
        if not address.get('street'):
            return False
        if not address.get('city'):
            return False
        if not address.get('zip'):
            return False
        return True
    
    # Security: Hardcoded encryption key
    def encrypt_tracking_data(self, data):
        key = "1234567890123456"  # Hardcoded key
        # Simplified encryption logic
        return data
    
    # Bug: File descriptor leak
    def log_shipment(self, shipment_id):
        f = open(f'/logs/shipment_{shipment_id}.log', 'a')
        f.write(f"{datetime.now()}: Shipment processed\n")
        # File not closed
    
    # Unused method
    def deprecated_calculate(self):
        pass
""",
            "test_shipping.py": """
import pytest
from shipping_service import ShippingService

def test_calculate_shipping():
    service = ShippingService()
    cost = service.calculate_shipping(10, 100)
    assert cost == 20.0

def test_track_package():
    service = ShippingService()
    result = service.track_package("TRACK123")
    assert result['status'] == 'in_transit'
""",
            "requirements.txt": """pytest==7.4.0
pytest-cov==4.1.0
pyyaml==6.0
# requests is missing - similar pattern to auth-api
""",
            "config.py": """
# Security: Exposed credentials
SHIPPING_PROVIDERS = {
    'fedex': {
        'api_key': 'fedex_production_key_12345',
        'secret': 'fedex_secret_67890'
    },
    'ups': {
        'username': 'ups_user',
        'password': 'ups_pass123'
    },
    'usps': {
        'user_id': 'usps_12345',
        'password': 'usps_password'
    }
}

DATABASE_CONFIG = {
    'host': 'localhost',
    'user': 'shipping_user',
    'password': 'shipping_pass123',
    'database': 'shipping_db'
}
""",
            "Dockerfile": """FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "shipping_service.py"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/python.yml'
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
            'description': 'CI/CD demonstration with various failure scenarios'
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
        
        # Create shared pipelines project first
        info("Creating shared pipelines repository...")
        shared_project = self.gl.projects.create({
            'name': 'shared-pipelines',
            'namespace_id': group.id,
            'description': 'Shared CI/CD pipeline templates'
        })
        
        # Commit shared templates
        self._commit_files(shared_project, SHARED_TEMPLATES, "feat: Add shared CI/CD templates")
        
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
                        info(f"    Added variable: {var['key']}")
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
            self._commit_files(project, config['files'], f"Initial commit: {config['language']} project")
            
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
            self.session.post(
                f"{self.url}/api/qualitygates/destroy",
                params={'name': QUALITY_GATE_NAME}
            )
        except:
            pass
            
        # Delete projects
        for project_name in PROJECTS:
            try:
                self.session.post(
                    f"{self.url}/api/projects/delete",
                    params={'project': project_name}
                )
            except:
                pass
                
        success("SonarQube cleanup complete")
        
    def create_quality_gate(self):
        """Create very strict quality gate"""
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
            
        # Add very strict conditions
        conditions = [
            # Coverage
            {'metric': 'new_coverage', 'op': 'LT', 'error': '80'},
            {'metric': 'coverage', 'op': 'LT', 'error': '70'},
            
            # Bugs - Zero tolerance
            {'metric': 'new_bugs', 'op': 'GT', 'error': '0'},
            {'metric': 'bugs', 'op': 'GT', 'error': '2'},
            
            # Vulnerabilities - Zero tolerance
            {'metric': 'new_vulnerabilities', 'op': 'GT', 'error': '0'},
            {'metric': 'vulnerabilities', 'op': 'GT', 'error': '1'},
            
            # Code Smells - Very strict
            {'metric': 'new_code_smells', 'op': 'GT', 'error': '3'},
            {'metric': 'code_smells', 'op': 'GT', 'error': '10'},
            
            # Duplications
            {'metric': 'new_duplicated_lines_density', 'op': 'GT', 'error': '3'},
            {'metric': 'duplicated_lines_density', 'op': 'GT', 'error': '5'},
            
            # Security Hotspots - Zero tolerance
            {'metric': 'new_security_hotspots', 'op': 'GT', 'error': '0'},
            {'metric': 'security_hotspots', 'op': 'GT', 'error': '2'},
            
            # Ratings must be A or B
            {'metric': 'reliability_rating', 'op': 'GT', 'error': '2'},
            {'metric': 'security_rating', 'op': 'GT', 'error': '2'},
            {'metric': 'sqale_rating', 'op': 'GT', 'error': '2'},
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
        
        success("Very strict quality gate created")
        
    def create_projects(self):
        """Create SonarQube projects"""
        for project_name in PROJECTS:
            info(f"Creating SonarQube project '{project_name}'...")
            
            # Create project
            response = self.session.post(
                f"{self.url}/api/projects/create",
                params={
                    'name': project_name,
                    'project': project_name
                }
            )
            
            if response.status_code != 400:
                response.raise_for_status()
                
            # Create webhook
            self.session.post(
                f"{self.url}/api/webhooks/create",
                params={
                    'name': 'CI/CD Assistant',
                    'project': project_name,
                    'url': f"{AGENT_WEBHOOK_URL}/sonarqube"
                }
            )
            
        success("SonarQube projects created")

def print_summary():
    """Print summary of created projects"""
    print("\n" + "="*80)
    success("Demo environment created successfully!")
    
    print("\n📦 PROJECTS CREATED (ALL WITH SONARQUBE ISSUES):")
    
    print("\n🚨 EXTENSIVE QUALITY ISSUES IN ALL PROJECTS:")
    print("  Every project contains:")
    print("    • Multiple security vulnerabilities (hardcoded passwords, SQL injection)")
    print("    • Several bugs (null pointers, resource leaks, race conditions)")
    print("    • Many code smells (duplicate code, complex methods, dead code)")
    print("    • Poor coverage (no tests for most code)")
    
    print("\n🔴 SPECIFIC FAILURES:")
    print("  • payment-service: MOST issues - SQL injection, weak crypto, memory leaks")
    print("  • auth-api: Build failure (missing jwt) + command injection, weak hashing")
    print("  • notification-service: Test failure + eval usage, hardcoded API keys")
    print("  • order-service: Package failure + insecure deserialization")
    print("  • inventory-api: Docker failure + thread safety issues")
    print("  • report-generator: Test failure (same pattern as notification)")
    print("  • shipping-service: Build failure (same pattern as auth-api)")
    
    print("\n🔗 SIMILAR PATTERNS FOR VECTOR DB:")
    print("  • Build failures: auth-api & shipping-service (missing dependency)")
    print("  • Test failures: notification-service & report-generator (off-by-one)")
    print("  • Security patterns: All projects have SQL injection vulnerabilities")
    print("  • Code smell patterns: All projects have duplicate code")
    
    print("\n⚙️ VERY STRICT QUALITY GATE RULES:")
    print("  • Zero new bugs/vulnerabilities allowed")
    print("  • Coverage: < 80% new, < 70% overall")
    print("  • Maximum 3 new code smells")
    print("  • Maximum 10 total code smells")
    print("  • All ratings must be A or B")
    print("  • Zero security hotspots allowed")
    
    print("\n✅ ALL PROJECTS WILL FAIL QUALITY GATES")
    print("   Perfect for demonstrating batch fixes in single MR")
    print("\n" + "="*80)

if __name__ == "__main__":
    print("=== Enhanced CI/CD Demo Environment Setup ===\n")
    
    # Get credentials
    gitlab_url = input("GitLab URL [http://localhost:8080]: ").strip() or "http://localhost:8080"
    gitlab_token = getpass.getpass("GitLab Token (with api scope): ")
    sonar_url = input("SonarQube URL [http://localhost:9001]: ").strip() or "http://localhost:9001"
    sonar_token = getpass.getpass("SonarQube Token: ")
    
    print(f"\nThis script will create:")
    print(f"- GitLab group '{GROUP_NAME}'")
    print(f"- 7 projects with extensive SonarQube issues")
    print(f"- Very strict quality gate")
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