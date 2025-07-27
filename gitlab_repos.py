#!/usr/bin/env python3
"""
CI/CD Environment Setup Script
Creates GitLab projects with various failure scenarios and SonarQube quality gates
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
GROUP_NAME = "envathon"
QUALITY_GATE_NAME = "envathon-gate"
AGENT_WEBHOOK_URL = "http://strands-agent:8000/webhook"

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

# Project definitions with various failure scenarios
PROJECTS = {
    # 1. Missing build artifacts scenario
    "payment-service": {
        "description": "Java microservice with missing build step",
        "failure_type": "build_artifact_missing",
        "files": {
            "src/main/java/com/envathon/payment/PaymentService.java": """
package com.envathon.payment;

import java.math.BigDecimal;
import java.util.UUID;

public class PaymentService {
    
    public PaymentResult processPayment(String customerId, BigDecimal amount) {
        // Security issue: logging sensitive data
        System.out.println("Processing payment for customer: " + customerId + " amount: " + amount);
        
        // Bug: no null check
        if (amount.compareTo(BigDecimal.ZERO) <= 0) {
            throw new IllegalArgumentException("Invalid amount");
        }
        
        // Code smell: magic number
        if (amount.compareTo(new BigDecimal(10000)) > 0) {
            return new PaymentResult(false, "Amount exceeds limit");
        }
        
        String transactionId = UUID.randomUUID().toString();
        // Vulnerability: weak random for sensitive operation
        boolean success = Math.random() > 0.1;
        
        return new PaymentResult(success, transactionId);
    }
    
    class PaymentResult {
        private boolean success;
        private String transactionId;
        
        public PaymentResult(boolean success, String transactionId) {
            this.success = success;
            this.transactionId = transactionId;
        }
    }
}
""",
            "pom.xml": """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 
         http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    
    <groupId>com.envathon</groupId>
    <artifactId>payment-service</artifactId>
    <version>1.0.0</version>
    <packaging>jar</packaging>
    
    <properties>
        <maven.compiler.source>11</maven.compiler.source>
        <maven.compiler.target>11</maven.compiler.target>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
    </properties>
    
    <dependencies>
        <dependency>
            <groupId>junit</groupId>
            <artifactId>junit</artifactId>
            <version>4.13.2</version>
            <scope>test</scope>
        </dependency>
    </dependencies>
</project>
""",
            "Dockerfile": """FROM openjdk:11-jre-slim
WORKDIR /app
# This will fail - no Maven build step to create the JAR
COPY target/payment-service-1.0.0.jar app.jar
EXPOSE 8080
CMD ["java", "-jar", "app.jar"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'envathon/shared-pipelines'
    ref: main
    file: '/templates/java-service.yml'

stages:
  - build
  - test
  - package

# Run SonarQube scan in parallel with build
sonar-analysis:
  extends: .sonar-scan
  stage: build
  variables:
    SONAR_JAVA_BINARIES: "target/classes"

# Intentionally missing Maven build stage
docker-build:
  extends: .docker-build
  stage: build
"""
        }
    },
    
    # 2. Dependency conflict scenario
    "user-service": {
        "description": "Python service with conflicting dependencies",
        "failure_type": "dependency_conflict",
        "files": {
            "app/main.py": """
import asyncio
import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging

# Configuration issue: hardcoded values
REDIS_HOST = "localhost"
REDIS_PORT = 6379

app = FastAPI()
logger = logging.getLogger(__name__)

class User(BaseModel):
    id: int
    name: str
    email: str
    password: str  # Security issue: plain text password

class UserService:
    def __init__(self):
        # Bug: no error handling for connection
        self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT)
        
    async def get_user(self, user_id: int) -> Optional[User]:
        # Performance issue: synchronous call in async function
        user_data = self.redis_client.get(f"user:{user_id}")
        if not user_data:
            return None
        
        # Bug: no error handling for JSON parsing
        return User(**json.loads(user_data))
    
    def save_user(self, user: User):
        # Security issue: storing password in plain text
        user_data = user.dict()
        self.redis_client.set(f"user:{user.id}", json.dumps(user_data))
        
        # Code smell: duplicate code
        logger.info(f"User saved: {user.id}")
        print(f"User saved: {user.id}")

# Initialization issue: service created at module level
user_service = UserService()

@app.get("/users/{user_id}")
async def get_user(user_id: int):
    user = await user_service.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@app.post("/users")
def create_user(user: User):
    # Async/sync mismatch
    user_service.save_user(user)
    return {"status": "created"}
""",
            "requirements.txt": """# Conflicting versions that will cause issues
fastapi==0.68.0
pydantic==2.5.0  # Incompatible with fastapi 0.68.0
redis==3.5.3
uvicorn==0.15.0
asyncio==3.4.3  # This is built-in, shouldn't be in requirements
requests==2.26.0
aioredis==1.3.1  # Conflicts with redis
""",
            "tests/test_user.py": """
import pytest
from app.main import User, UserService

def test_user_creation():
    # Test without mocking Redis - will fail in CI
    service = UserService()
    user = User(id=1, name="Test", email="test@example.com", password="secret")
    service.save_user(user)
    
    # No assertion - bad test practice
    
def test_invalid_user():
    # Test will pass but doesn't test anything meaningful
    assert True
""",
            "Dockerfile": """FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
# This will fail due to dependency conflicts
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'envathon/shared-pipelines'
    ref: main
    file: '/templates/python-service.yml'

stages:
  - build
  - test

# Run SonarQube scan in parallel with dependency installation
sonar-analysis:
  extends: .sonar-scan
  stage: build
  variables:
    SONAR_PYTHON_VERSION: "3.9"

install-deps:
  stage: build
  extends: .python-deps
  script:
    - pip install -r requirements.txt  # Will fail
"""
        }
    },
    
    # 3. Test failure scenario
    "inventory-service": {
        "description": "Node.js service with failing tests",
        "failure_type": "test_failure",
        "files": {
            "src/inventory.js": """
const express = require('express');
const app = express();

// Global state - bad practice
let inventory = {};

class InventoryManager {
    constructor() {
        // Memory leak: never cleared
        this.cache = new Map();
        this.listeners = [];
    }
    
    addItem(itemId, quantity) {
        // Bug: no validation
        inventory[itemId] = (inventory[itemId] || 0) + quantity;
        
        // Performance issue: O(n) notification
        this.listeners.forEach(listener => {
            listener(itemId, inventory[itemId]);
        });
        
        // Memory leak: unbounded cache
        this.cache.set(Date.now(), { itemId, quantity });
    }
    
    removeItem(itemId, quantity) {
        // Bug: can go negative
        inventory[itemId] = (inventory[itemId] || 0) - quantity;
        
        // Code smell: duplicate notification logic
        this.listeners.forEach(listener => {
            listener(itemId, inventory[itemId]);
        });
    }
    
    getStock(itemId) {
        // Inconsistent return types
        return inventory[itemId] || "Out of stock";
    }
}

const manager = new InventoryManager();

app.post('/inventory/:id/add', (req, res) => {
    const { id } = req.params;
    const { quantity } = req.body;
    
    // Security: no input validation
    manager.addItem(id, quantity);
    
    // Security: exposing internal state
    res.json({ success: true, inventory });
});

app.get('/inventory/:id', (req, res) => {
    const stock = manager.getStock(req.params.id);
    res.json({ stock });
});

// Hardcoded port
const server = app.listen(3000);

module.exports = { InventoryManager, app, server };
""",
            "tests/inventory.test.js": """
const { InventoryManager } = require('../src/inventory');

describe('InventoryManager', () => {
    let manager;
    
    beforeEach(() => {
        manager = new InventoryManager();
    });
    
    test('should add items to inventory', () => {
        manager.addItem('item1', 10);
        // This will fail - getStock returns "Out of stock" string for missing items
        expect(manager.getStock('item1')).toBe(10);
    });
    
    test('should handle negative inventory', () => {
        manager.removeItem('item2', 5);
        // This will fail - expecting 0 but gets -5
        expect(manager.getStock('item2')).toBe(0);
    });
    
    test('should notify listeners', () => {
        const mockListener = jest.fn();
        manager.listeners.push(mockListener);
        
        manager.addItem('item3', 1);
        
        // This will fail - listeners is private
        expect(mockListener).toHaveBeenCalledWith('item3', 1);
    });
});
""",
            "package.json": """{
  "name": "inventory-service",
  "version": "1.0.0",
  "scripts": {
    "test": "jest --forceExit --detectOpenHandles",
    "start": "node src/inventory.js"
  },
  "dependencies": {
    "express": "^4.18.0"
  },
  "devDependencies": {
    "jest": "^27.0.0"
  }
}
""",
            ".gitlab-ci.yml": """include:
  - project: 'envathon/shared-pipelines'
    ref: main
    file: '/templates/nodejs-service.yml'

stages:
  - build
  - test

# Run SonarQube scan in parallel with tests
sonar-analysis:
  extends: .sonar-scan
  stage: build

test:
  extends: .node-test
  stage: test
  script:
    - npm install
    - npm test  # Will fail
"""
        }
    },
    
    # 4. Quality gate failure scenario
    "analytics-engine": {
        "description": "Python data processing with quality issues",
        "failure_type": "quality_gate_failure",
        "files": {
            "analytics/processor.py": """
import pandas as pd
import numpy as np
from datetime import datetime
import json

class DataProcessor:
    def __init__(self):
        # Code smell: too many instance variables
        self.data = None
        self.results = None
        self.errors = []
        self.warnings = []
        self.metadata = {}
        self.cache = {}
        self.temp_data = None
        self.config = None
        self.status = "idle"
        
    def process_data(self, file_path):
        # Cognitive complexity too high
        try:
            if file_path.endswith('.csv'):
                self.data = pd.read_csv(file_path)
                
                # Duplicate code block 1
                if self.data.empty:
                    self.errors.append("Empty dataset")
                    self.status = "error"
                    return None
                    
                # Nested if statements - complexity
                if 'timestamp' in self.data.columns:
                    if self.data['timestamp'].dtype == 'object':
                        try:
                            self.data['timestamp'] = pd.to_datetime(self.data['timestamp'])
                            if self.data['timestamp'].isnull().any():
                                self.warnings.append("Null timestamps found")
                                if len(self.warnings) > 10:
                                    self.status = "warning"
                        except:
                            self.errors.append("Timestamp parsing failed")
                            
            elif file_path.endswith('.json'):
                with open(file_path) as f:
                    raw_data = json.load(f)
                self.data = pd.DataFrame(raw_data)
                
                # Duplicate code block 2 (same as block 1)
                if self.data.empty:
                    self.errors.append("Empty dataset")
                    self.status = "error"
                    return None
                    
            # Long method with multiple responsibilities
            self._validate_data()
            self._clean_data()
            self._transform_data()
            self._aggregate_data()
            self._generate_report()
            
        except Exception as e:
            # Generic exception handling
            self.errors.append(str(e))
            
    def _validate_data(self):
        # Duplicate validation logic
        required_columns = ['id', 'value', 'timestamp']
        for col in required_columns:
            if col not in self.data.columns:
                self.errors.append(f"Missing column: {col}")
                
    def _clean_data(self):
        # Inefficient cleaning
        for idx, row in self.data.iterrows():
            if pd.isnull(row['value']):
                self.data.drop(idx, inplace=True)
                
    def _transform_data(self):
        # Complex transformation with side effects
        self.temp_data = self.data.copy()
        self.data['value_squared'] = self.data['value'] ** 2
        self.data['value_log'] = np.log(self.data['value'])
        
    def _aggregate_data(self):
        # Unused variable
        total_count = len(self.data)
        
        # Magic numbers
        if len(self.data) > 1000:
            sample_size = 100
        else:
            sample_size = 50
            
        self.results = {
            'mean': self.data['value'].mean(),
            'std': self.data['value'].std(),
            'sample': self.data.head(sample_size)
        }
        
    def _generate_report(self):
        # Dead code
        if False:
            print("This never executes")
            
        # Duplicate reporting logic
        print(f"Processing complete: {len(self.data)} records")
        self.metadata['record_count'] = len(self.data)

# Global instance - bad practice
processor = DataProcessor()

def main():
    # Hardcoded path
    processor.process_data('/data/analytics.csv')
    
if __name__ == "__main__":
    main()
""",
            "analytics/utils.py": """
# Utility functions with code smells

def calculate_metrics(data):
    # Function too long
    # Missing docstring
    result = {}
    
    # Duplicate calculation 1
    if len(data) > 0:
        result['mean'] = sum(data) / len(data)
        result['min'] = min(data)
        result['max'] = max(data)
    else:
        result['mean'] = 0
        result['min'] = 0
        result['max'] = 0
        
    # Complex nested logic
    if result['mean'] > 0:
        if result['max'] > result['mean'] * 2:
            if result['min'] < result['mean'] / 2:
                result['variance'] = 'high'
            else:
                result['variance'] = 'medium'
        else:
            result['variance'] = 'low'
    else:
        result['variance'] = 'none'
        
    # Duplicate calculation 2
    if len(data) > 0:
        result['sum'] = sum(data)
        result['count'] = len(data)
    else:
        result['sum'] = 0
        result['count'] = 0
        
    return result

def unused_function():
    # Dead code
    pass
    
def another_unused_function(param1, param2):
    # More dead code
    return param1 + param2
""",
            "requirements.txt": """pandas==1.3.0
numpy==1.21.0
""",
            ".gitlab-ci.yml": """include:
  - project: 'envathon/shared-pipelines'
    ref: main
    file: '/templates/python-service.yml'

stages:
  - build
  - test

# Run SonarQube scan immediately
sonar-analysis:
  extends: .sonar-scan
  stage: build
  variables:
    SONAR_SOURCES: "analytics"
    SONAR_PYTHON_VERSION: "3.9"

# Run tests in parallel
test:
  extends: .python-test
  stage: build
  script:
    - pip install -r requirements.txt
    - python -m pytest --version 2>/dev/null || echo "No tests"
"""
        }
    },
    
    # 5. Performance/timeout scenario
    "report-generator": {
        "description": "Java service with performance issues",
        "failure_type": "timeout",
        "files": {
            "src/main/java/com/envathon/reports/ReportGenerator.java": """
package com.envathon.reports;

import java.util.*;
import java.sql.*;

public class ReportGenerator {
    
    // Resource leak: connection never closed
    private Connection dbConnection;
    
    public ReportGenerator() {
        try {
            dbConnection = DriverManager.getConnection(
                "jdbc:postgresql://localhost:5432/reports",
                "user", "password"  // Security: hardcoded credentials
            );
        } catch (SQLException e) {
            // Swallowing exception
        }
    }
    
    public List<Report> generateReports(Date startDate, Date endDate) {
        List<Report> reports = new ArrayList<>();
        
        // Performance: N+1 query problem
        List<Integer> userIds = getAllUserIds();
        for (Integer userId : userIds) {
            User user = getUser(userId);  // Individual query per user
            
            // Performance: nested loops
            for (Date date = startDate; date.before(endDate); date = addDay(date)) {
                List<Transaction> transactions = getTransactions(userId, date);
                
                // O(n²) complexity
                for (Transaction t1 : transactions) {
                    for (Transaction t2 : transactions) {
                        if (t1.getId() != t2.getId()) {
                            // Expensive operation in nested loop
                            checkDuplicate(t1, t2);
                        }
                    }
                }
                
                Report report = new Report(user, date, transactions);
                reports.add(report);
            }
        }
        
        // Memory issue: loading all data
        return reports;
    }
    
    private List<Integer> getAllUserIds() {
        // Inefficient: loading all users
        String query = "SELECT id FROM users";  // No limit
        // Implementation that loads millions of records
        return Arrays.asList(1, 2, 3); // Simplified
    }
    
    private User getUser(int userId) {
        // SQL injection vulnerability
        String query = "SELECT * FROM users WHERE id = " + userId;
        // Implementation
        return new User();
    }
    
    private List<Transaction> getTransactions(int userId, Date date) {
        // Slow query without index
        String query = "SELECT * FROM transactions WHERE user_id = ? AND date = ?";
        // Implementation
        return new ArrayList<>();
    }
    
    private void checkDuplicate(Transaction t1, Transaction t2) {
        // Expensive operation
        try {
            Thread.sleep(100); // Simulating slow operation
        } catch (InterruptedException e) {
            // Bad practice: interrupting thread
        }
    }
    
    private Date addDay(Date date) {
        Calendar cal = Calendar.getInstance();
        cal.setTime(date);
        cal.add(Calendar.DATE, 1);
        return cal.getTime();
    }
    
    class Report {}
    class User {}
    class Transaction {
        int getId() { return 0; }
    }
}
""",
            "src/test/java/com/envathon/reports/ReportGeneratorTest.java": """
package com.envathon.reports;

import org.junit.Test;
import java.util.Date;

public class ReportGeneratorTest {
    
    @Test(timeout = 5000)  // 5 second timeout
    public void testReportGeneration() {
        ReportGenerator generator = new ReportGenerator();
        
        Date start = new Date();
        Date end = new Date(start.getTime() + 30 * 24 * 60 * 60 * 1000L); // 30 days
        
        // This will timeout due to performance issues
        generator.generateReports(start, end);
    }
}
""",
            "pom.xml": """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 
         http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    
    <groupId>com.envathon</groupId>
    <artifactId>report-generator</artifactId>
    <version>1.0.0</version>
    
    <properties>
        <maven.compiler.source>11</maven.compiler.source>
        <maven.compiler.target>11</maven.compiler.target>
    </properties>
    
    <dependencies>
        <dependency>
            <groupId>junit</groupId>
            <artifactId>junit</artifactId>
            <version>4.13.2</version>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>org.postgresql</groupId>
            <artifactId>postgresql</artifactId>
            <version>42.2.23</version>
        </dependency>
    </dependencies>
    
    <build>
        <plugins>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-surefire-plugin</artifactId>
                <version>2.22.2</version>
                <configuration>
                    <forkedProcessTimeoutInSeconds>10</forkedProcessTimeoutInSeconds>
                </configuration>
            </plugin>
        </plugins>
    </build>
</project>
""",
            ".gitlab-ci.yml": """include:
  - project: 'envathon/shared-pipelines'
    ref: main
    file: '/templates/java-service.yml'

stages:
  - build
  - test

# Run SonarQube scan in parallel with tests
sonar-analysis:
  extends: .sonar-scan
  stage: build
  variables:
    SONAR_JAVA_BINARIES: "target/classes"
    SONAR_JAVA_SOURCE: "11"

# Maven build first
build:
  extends: .java-build
  stage: build

test:
  extends: .java-test
  stage: test
  timeout: 2 minutes  # Will timeout
  dependencies:
    - build
"""
        }
    },
    
    # 6. Working project for contrast
    "health-check-service": {
        "description": "Simple service that passes all checks",
        "failure_type": "none",
        "files": {
            "src/health.py": """
\"\"\"
Health check service for monitoring system status.
\"\"\"
from fastapi import FastAPI
from datetime import datetime
from typing import Dict

app = FastAPI(title="Health Check Service")

@app.get("/health")
def health_check() -> Dict[str, str]:
    \"\"\"Return health status of the service.\"\"\"
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "health-check"
    }

@app.get("/ready")
def readiness_check() -> Dict[str, bool]:
    \"\"\"Check if service is ready to handle requests.\"\"\"
    return {"ready": True}
""",
            "tests/test_health.py": """
import pytest
from fastapi.testclient import TestClient
from src.health import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data

def test_readiness():
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["ready"] is True
""",
            "requirements.txt": """fastapi==0.104.1
uvicorn==0.24.0
pytest==7.4.3
httpx==0.25.1
""",
            ".gitlab-ci.yml": """include:
  - project: 'envathon/shared-pipelines'
    ref: main
    file: '/templates/python-service.yml'

stages:
  - build
  - test

# Run SonarQube scan in parallel with tests
sonar-analysis:
  extends: .sonar-scan
  stage: build

test:
  extends: .python-test
  stage: build
  coverage: '/TOTAL.*\\s+(\\d+%)$/'
"""
        }
    }
}

# Shared CI/CD templates
SHARED_TEMPLATES = {
    "templates/base.yml": """
variables:
  DOCKER_DRIVER: overlay2
  DOCKER_TLS_CERTDIR: ""
  SONAR_USER_HOME: "${CI_PROJECT_DIR}/.sonar"
  GIT_DEPTH: "0"

stages:
  - build
  - test
  - deploy

.docker-build:
  image: docker:24.0.5
  stage: build
  services:
    - docker:24.0.5-dind
  before_script:
    - docker info
  script:
    - docker build -t ${CI_PROJECT_NAME}:${CI_COMMIT_SHORT_SHA} .

.sonar-scan:
  image: sonarsource/sonar-scanner-cli:latest
  stage: build  # Run in parallel with build
  cache:
    key: "${CI_JOB_NAME}"
    paths:
      - .sonar/cache
  script:
    - |
      sonar-scanner \
        -Dsonar.projectKey=${SONAR_PROJECT_KEY} \
        -Dsonar.host.url=${SONAR_HOST_URL} \
        -Dsonar.token=${SONAR_TOKEN} \
        -Dsonar.sources=. \
        -Dsonar.projectName=${CI_PROJECT_NAME} \
        -Dsonar.projectVersion=${CI_COMMIT_SHORT_SHA} \
        -Dsonar.qualitygate.wait=true
  allow_failure: false  # Fail pipeline if quality gate fails
""",
    "templates/java-service.yml": """
include:
  - local: '/templates/base.yml'

.java-build:
  image: maven:3.8-openjdk-11
  stage: build
  cache:
    paths:
      - .m2/repository
  script:
    - mvn clean compile

.java-test:
  extends: .java-build
  script:
    - mvn test
  artifacts:
    reports:
      junit:
        - target/surefire-reports/TEST-*.xml

.java-package:
  extends: .java-build
  script:
    - mvn package
  artifacts:
    paths:
      - target/*.jar

# Java-specific SonarQube configuration
.java-sonar:
  extends: .sonar-scan
  variables:
    SONAR_JAVA_BINARIES: "target/classes"
    SONAR_JAVA_LIBRARIES: ".m2/repository/**/*.jar"
    SONAR_JAVA_TEST_BINARIES: "target/test-classes"
    SONAR_JUNIT_REPORT_PATHS: "target/surefire-reports"
""",
    "templates/python-service.yml": """
include:
  - local: '/templates/base.yml'

.python-deps:
  image: python:3.9
  stage: build
  cache:
    paths:
      - .cache/pip
  before_script:
    - pip install --upgrade pip
    - pip install virtualenv
    - virtualenv venv
    - source venv/bin/activate

.python-test:
  extends: .python-deps
  script:
    - pip install -r requirements.txt
    - pip install pytest pytest-cov
    - pytest --cov=. --cov-report=term --cov-report=xml
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml

# Python-specific SonarQube configuration
.python-sonar:
  extends: .sonar-scan
  variables:
    SONAR_PYTHON_COVERAGE_REPORTPATHS: "coverage.xml"
    SONAR_PYTHON_XUNIT_REPORTPATH: "test-results/*.xml"
""",
    "templates/nodejs-service.yml": """
include:
  - local: '/templates/base.yml'

.node-deps:
  image: node:16
  cache:
    paths:
      - node_modules/
  before_script:
    - npm ci || npm install

.node-test:
  extends: .node-deps
  script:
    - npm test
  artifacts:
    reports:
      junit:
        - junit.xml
""",
    "templates/python-quality.yml": """
include:
  - local: '/templates/base.yml'

.python-lint:
  image: python:3.9
  script:
    - pip install flake8 pylint black
    - flake8 . || true
    - pylint **/*.py || true
    - black --check . || true
"""
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
                info("Waiting for deletion to complete...")
                time.sleep(5)
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
            'description': 'CI/CD failure demonstration environment'
        })
        
        # Set group variables
        info("Setting group-level CI/CD variables...")
        group.variables.create({'key': 'SONAR_HOST_URL', 'value': sonar_url})
        group.variables.create({'key': 'SONAR_TOKEN', 'value': sonar_token, 'masked': True})
        group.variables.create({'key': 'DOCKER_REGISTRY', 'value': 'registry.gitlab.com'})
        
        # Create shared pipelines project
        info("Creating shared pipelines repository...")
        shared_project = self.gl.projects.create({
            'name': 'shared-pipelines',
            'namespace_id': group.id,
            'description': 'Shared CI/CD pipeline templates'
        })
        
        # Commit shared templates
        self._commit_files(shared_project, SHARED_TEMPLATES, "Initial pipeline templates")
        
        # Create application projects
        for project_name, config in PROJECTS.items():
            info(f"Creating project '{project_name}'...")
            project = self.gl.projects.create({
                'name': project_name,
                'namespace_id': group.id,
                'description': config['description']
            })
            
            # Set project variables
            project.variables.create({
                'key': 'SONAR_PROJECT_KEY',
                'value': f"{GROUP_NAME}_{project_name}"
            })
            
            # Create webhook
            project.hooks.create({
                'url': f"{AGENT_WEBHOOK_URL}/gitlab",
                'pipeline_events': True,
                'push_events': True,
                'merge_requests_events': True
            })
            
            # Commit project files
            self._commit_files(project, config['files'], f"Initial commit - {config['failure_type']}")
            
        success(f"GitLab environment created: {group.web_url}")
        
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
                    params={'project': f"{GROUP_NAME}_{project_name}"}
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
            # Code coverage
            {'metric': 'new_coverage', 'op': 'LT', 'error': '80'},
            {'metric': 'new_line_coverage', 'op': 'LT', 'error': '80'},
            
            # Reliability
            {'metric': 'new_reliability_rating', 'op': 'GT', 'error': '1'},
            {'metric': 'new_bugs', 'op': 'GT', 'error': '0'},
            
            # Security
            {'metric': 'new_security_rating', 'op': 'GT', 'error': '1'},
            {'metric': 'new_vulnerabilities', 'op': 'GT', 'error': '0'},
            {'metric': 'new_security_hotspots_reviewed', 'op': 'LT', 'error': '100'},
            
            # Maintainability
            {'metric': 'new_maintainability_rating', 'op': 'GT', 'error': '1'},
            {'metric': 'new_code_smells', 'op': 'GT', 'error': '5'},
            {'metric': 'new_technical_debt_ratio', 'op': 'GT', 'error': '5'},
            
            # Duplications
            {'metric': 'new_duplicated_lines_density', 'op': 'GT', 'error': '3'},
            
            # Complexity
            {'metric': 'complexity', 'op': 'GT', 'error': '20'},
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
        """Create SonarQube projects"""
        for project_name in PROJECTS:
            key = f"{GROUP_NAME}_{project_name}"
            info(f"Creating SonarQube project '{key}'...")
            
            # Create project
            response = self.session.post(
                f"{self.url}/api/projects/create",
                params={'name': project_name, 'project': key}
            )
            
            if response.status_code != 400:  # 400 = already exists
                response.raise_for_status()
                
            # Create webhook
            self.session.post(
                f"{self.url}/api/webhooks/create",
                params={
                    'name': 'CI/CD Assistant',
                    'project': key,
                    'url': f"{AGENT_WEBHOOK_URL}/sonarqube"
                }
            )
            
        success("SonarQube projects created")

if __name__ == "__main__":
    print("=== CI/CD Failure Analysis Environment Setup ===\n")
    
    # Get credentials
    global sonar_url, sonar_token
    gitlab_url = input("GitLab URL [http://localhost:8080]: ").strip() or "http://localhost:8080"
    gitlab_token = getpass.getpass("GitLab Token (api scope): ")
    sonar_url = input("SonarQube URL [http://localhost:9001]: ").strip() or "http://localhost:9001"
    sonar_token = getpass.getpass("SonarQube Token: ")
    
    print("\nThis script will:")
    print(f"- Create GitLab group '{GROUP_NAME}' with shared CI/CD templates")
    print(f"- Create {len(PROJECTS)} projects with various failure scenarios")
    print(f"- Create SonarQube quality gate '{QUALITY_GATE_NAME}' with strict rules")
    print("- Configure webhooks for failure notifications")
    
    if input("\nProceed? (yes/no): ").lower() != 'yes':
        print("Cancelled")
        sys.exit(0)
        
    try:
        # Initialize managers
        gitlab_manager = GitLabSetup(gitlab_url, gitlab_token)
        sonar_manager = SonarQubeSetup(sonar_url, sonar_token)
        
        # Cleanup
        gitlab_manager.cleanup()
        sonar_manager.cleanup()
        
        # Create environment
        sonar_manager.create_quality_gate()
        sonar_manager.create_projects()
        gitlab_manager.create_environment()
        
        print("\n" + "="*50)
        success("Setup complete! Created projects with failures:")
        print(f"  • payment-service: Missing Maven build → Docker failure")
        print(f"  • user-service: Dependency conflicts → Install failure")
        print(f"  • inventory-service: Failing unit tests")
        print(f"  • analytics-engine: Quality gate violations")
        print(f"  • report-generator: Performance timeout")
        print(f"  • health-check-service: ✓ Passes all checks")
        
    except Exception as e:
        error(f"Setup failed: {e}")