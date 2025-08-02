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
    # 1. Java - Payment Service (SonarQube quality gate failures)
    "payment-service": {
        "description": "Payment service with multiple SonarQube issues",
        "language": "java",
        "template": "java-maven.yml",
        "files": {
            "src/main/java/com/demo/payment/PaymentService.java": """
package com.demo.payment;

import java.sql.*;
import java.util.Random;

public class PaymentService {
    private static final String PASSWORD = "admin123"; // Security vulnerability
    
    // Bug: SQL Injection vulnerability
    public boolean processPayment(String userId, double amount) throws SQLException {
        String query = "SELECT balance FROM users WHERE id = '" + userId + "'";
        Connection conn = DriverManager.getConnection("jdbc:h2:mem:test", "sa", PASSWORD);
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
                return true;
            }
        }
        return false;
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
    
    // Security: Weak random number generator
    public String generateTransactionId() {
        Random rand = new Random();
        return "TXN" + rand.nextInt(10000);
    }
    
    // Unused method (code smell)
    private void oldMethod() {
        System.out.println("This method is never used");
    }
}
""",
            "src/main/java/com/demo/payment/CreditCardValidator.java": """
package com.demo.payment;

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
            cardNumber.startsWith("37") || cardNumber.startsWith("6")) {
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

    # 2. Python - Auth API (Build failure - missing dependency)
    "auth-api": {
        "description": "Auth API with build failure due to missing dependency",
        "language": "python",
        "template": "python.yml",
        "files": {
            "auth_service.py": """
import jwt  # Missing from requirements.txt
import hashlib
from datetime import datetime, timedelta

class AuthService:
    SECRET_KEY = "secret123"  # Security issue
    
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
        except:
            return None
    
    def hash_password(self, password):
        # Security: Weak hashing
        return hashlib.md5(password.encode()).hexdigest()
""",
            "test_auth.py": """
import pytest
from auth_service import AuthService

def test_hash_password():
    service = AuthService()
    hashed = service.hash_password("test123")
    assert len(hashed) == 32
""",
            "requirements.txt": """pytest==7.4.0
pytest-cov==4.1.0
# jwt is missing - will cause build failure
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

    # 3. Node.js - Notification Service (Test failure)
    "notification-service": {
        "description": "Notification service with failing tests",
        "language": "javascript",
        "template": "nodejs.yml",
        "files": {
            "notification.js": """
class NotificationService {
    constructor() {
        this.notifications = [];
    }
    
    sendEmail(to, subject, body) {
        if (!to || !subject) {
            throw new Error('Missing required fields');
        }
        
        const notification = {
            id: Date.now(),
            type: 'email',
            to,
            subject,
            body,
            sent: new Date()
        };
        
        this.notifications.push(notification);
        return notification;
    }
    
    getNotifications(type) {
        return this.notifications.filter(n => n.type === type);
    }
    
    // Bug: Returns wrong count
    getCount() {
        return this.notifications.length + 1; // Off by one error
    }
}

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

    # 4. Python - Order Service (Package failure)
    "order-service": {
        "description": "Order service with package stage failure",
        "language": "python",
        "template": "python.yml",
        "files": {
            "order_service.py": """
class OrderService:
    def __init__(self):
        self.orders = {}
    
    def create_order(self, user_id, items):
        order_id = len(self.orders) + 1
        self.orders[order_id] = {
            'user_id': user_id,
            'items': items,
            'status': 'pending'
        }
        return order_id
    
    def get_order(self, order_id):
        return self.orders.get(order_id)
""",
            "test_order.py": """
import pytest
from order_service import OrderService

def test_create_order():
    service = OrderService()
    order_id = service.create_order('user123', ['item1', 'item2'])
    assert order_id == 1
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

    # 5. Java - Inventory API (Docker build failure)
    "inventory-api": {
        "description": "Inventory API with Docker build failure",
        "language": "java",
        "template": "java-maven.yml",
        "files": {
            "src/main/java/com/demo/inventory/InventoryService.java": """
package com.demo.inventory;

import java.util.HashMap;
import java.util.Map;

public class InventoryService {
    private Map<String, Integer> inventory = new HashMap<>();
    
    public void addItem(String itemId, int quantity) {
        inventory.put(itemId, inventory.getOrDefault(itemId, 0) + quantity);
    }
    
    public boolean checkAvailability(String itemId, int quantity) {
        return inventory.getOrDefault(itemId, 0) >= quantity;
    }
    
    public void removeItem(String itemId, int quantity) {
        int current = inventory.getOrDefault(itemId, 0);
        inventory.put(itemId, Math.max(0, current - quantity));
    }
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

    # 6. Node.js - Report Generator (Similar error pattern for vector DB demo)
    "report-generator": {
        "description": "Report generator with similar test failure pattern",
        "language": "javascript",
        "template": "nodejs.yml",
        "files": {
            "report.js": """
class ReportGenerator {
    constructor() {
        this.reports = [];
    }
    
    generateReport(type, data) {
        const report = {
            id: this.reports.length + 1,
            type,
            data,
            timestamp: new Date()
        };
        
        this.reports.push(report);
        return report;
    }
    
    // Bug: Returns wrong count (similar to notification-service)
    getReportCount() {
        return this.reports.length + 1; // Off by one error
    }
    
    getReportsByType(type) {
        return this.reports.filter(r => r.type === type);
    }
}

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

    # 7. Python - Shipping Service (Multiple similar patterns)
    "shipping-service": {
        "description": "Shipping service with pattern similar to auth-api",
        "language": "python",
        "template": "python.yml",
        "files": {
            "shipping_service.py": """
import requests  # Missing from requirements.txt - similar to auth-api
from datetime import datetime

class ShippingService:
    API_KEY = "shipping123"  # Security issue
    
    def calculate_shipping(self, weight, distance):
        base_rate = 5.0
        return base_rate + (weight * 0.5) + (distance * 0.1)
    
    def track_package(self, tracking_id):
        # Would normally call external API
        return {
            'id': tracking_id,
            'status': 'in_transit',
            'location': 'Unknown'
        }
    
    def create_label(self, order_data):
        # Similar pattern - missing dependency will cause failure
        response = requests.post('https://api.shipping.com/labels', 
                               json=order_data,
                               headers={'Authorization': self.API_KEY})
        return response.json()
""",
            "test_shipping.py": """
import pytest
from shipping_service import ShippingService

def test_calculate_shipping():
    service = ShippingService()
    cost = service.calculate_shipping(10, 100)
    assert cost == 20.0
""",
            "requirements.txt": """pytest==7.4.0
pytest-cov==4.1.0
# requests is missing - similar pattern to auth-api
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
        """Create strict quality gate"""
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
            
        # Add strict conditions
        conditions = [
            # Coverage
            {'metric': 'new_coverage', 'op': 'LT', 'error': '80'},
            {'metric': 'coverage', 'op': 'LT', 'error': '60'},
            
            # Bugs
            {'metric': 'new_bugs', 'op': 'GT', 'error': '0'},
            {'metric': 'bugs', 'op': 'GT', 'error': '5'},
            
            # Vulnerabilities
            {'metric': 'new_vulnerabilities', 'op': 'GT', 'error': '0'},
            {'metric': 'vulnerabilities', 'op': 'GT', 'error': '3'},
            
            # Code Smells
            {'metric': 'new_code_smells', 'op': 'GT', 'error': '3'},
            {'metric': 'code_smells', 'op': 'GT', 'error': '20'},
            
            # Duplications
            {'metric': 'new_duplicated_lines_density', 'op': 'GT', 'error': '5'},
            {'metric': 'duplicated_lines_density', 'op': 'GT', 'error': '10'},
            
            # Security
            {'metric': 'new_security_hotspots', 'op': 'GT', 'error': '0'},
            {'metric': 'security_rating', 'op': 'GT', 'error': '2'},
            
            # Maintainability
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
        
        success("Strict quality gate created")
        
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
    
    print("\n📦 PROJECTS CREATED:")
    
    print("\n🚨 SONARQUBE QUALITY GATE FAILURES:")
    print("  • payment-service: Multiple bugs, vulnerabilities, code smells, security issues")
    print("    - SQL injection vulnerability")
    print("    - Hardcoded passwords")
    print("    - Resource leaks")
    print("    - Duplicate code")
    
    print("\n🔴 BUILD FAILURES:")
    print("  • auth-api: Missing 'jwt' dependency")
    print("  • shipping-service: Missing 'requests' dependency (similar pattern)")
    
    print("\n❌ TEST FAILURES:")
    print("  • notification-service: Off-by-one error in getCount()")
    print("  • report-generator: Same off-by-one pattern (vector DB demo)")
    
    print("\n📦 PACKAGE FAILURES:")
    print("  • order-service: Syntax error in setup.py")
    
    print("\n🐳 DOCKER BUILD FAILURES:")
    print("  • inventory-api: Wrong JAR file path in Dockerfile")
    
    print("\n🔗 SIMILAR PATTERNS FOR VECTOR DB:")
    print("  • auth-api & shipping-service: Missing dependency pattern")
    print("  • notification-service & report-generator: Off-by-one error pattern")
    
    print("\n⚙️ QUALITY GATE RULES (STRICT):")
    print("  • Coverage: < 80% (new), < 60% (overall)")
    print("  • Zero tolerance for new bugs/vulnerabilities")
    print("  • Maximum 3 new code smells")
    print("  • Security rating must be A or B")
    
    print("\n✅ KEY FEATURES:")
    print("  • No 'scan-image' stage (removed)")
    print("  • Jest tests with --watchAll=false (no hanging)")
    print("  • Moderate code complexity")
    print("  • Clear failure patterns for demo")
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
    print(f"- 7 projects with various failure scenarios")
    print(f"- Strict SonarQube quality gate")
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