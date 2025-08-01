#!/usr/bin/env python3
"""
CI/CD Demo Environment Setup Script
Creates GitLab projects with various failure scenarios
Includes shared pipeline templates and CI/CD variables
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
    {'key': 'SKIP_IMAGE_PUSH', 'value': 'true'},
]

# Project-specific variables
PROJECT_VARIABLES = {
    "calculator-service": [
        {'key': 'SERVICE_NAME', 'value': 'calculator-service'},
        {'key': 'JAVA_VERSION', 'value': '11'},
        {'key': 'MAVEN_OPTS', 'value': '-Xmx1024m'},
        {'key': 'SONAR_SOURCES', 'value': 'src/main/java'},
        {'key': 'SONAR_JAVA_BINARIES', 'value': 'target/classes'},
        {'key': 'SONAR_PROJECT_KEY', 'value': 'calculator-service'},
    ],
    "todo-api": [
        {'key': 'SERVICE_NAME', 'value': 'todo-api'},
        {'key': 'PYTHON_VERSION', 'value': '3.9'},
        {'key': 'SONAR_SOURCES', 'value': '.'},
        {'key': 'SONAR_PYTHON_VERSION', 'value': '3.9'},
        {'key': 'SONAR_PROJECT_KEY', 'value': 'todo-api'},
    ],
    "weather-service": [
        {'key': 'SERVICE_NAME', 'value': 'weather-service'},
        {'key': 'NODE_VERSION', 'value': '16'},
        {'key': 'SONAR_SOURCES', 'value': '.'},
        {'key': 'NPM_CONFIG_CACHE', 'value': '.npm'},
        {'key': 'SONAR_PROJECT_KEY', 'value': 'weather-service'},
    ],
    "user-service": [
        {'key': 'SERVICE_NAME', 'value': 'user-service'},
        {'key': 'PYTHON_VERSION', 'value': '3.9'},
        {'key': 'SONAR_SOURCES', 'value': '.'},
        {'key': 'SONAR_PROJECT_KEY', 'value': 'user-service'},
    ],
    "library-manager": [
        {'key': 'SERVICE_NAME', 'value': 'library-manager'},
        {'key': 'JAVA_VERSION', 'value': '11'},
        {'key': 'SONAR_SOURCES', 'value': 'src/main/java'},
        {'key': 'SONAR_JAVA_BINARIES', 'value': 'target/classes'},
        {'key': 'SONAR_PROJECT_KEY', 'value': 'library-manager'},
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
  - scan

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
  stage: package
  extends: 
    - .docker-base
    - .base-rules
  needs: ["package"]
  script:
    - docker build -t ${SERVICE_NAME:-$CI_PROJECT_NAME}:$CI_COMMIT_SHORT_SHA .
    - docker save ${SERVICE_NAME:-$CI_PROJECT_NAME}:$CI_COMMIT_SHORT_SHA > image.tar
  artifacts:
    paths:
      - image.tar
    expire_in: 1 hour

# Scan Docker image
scan-image:
  stage: scan
  image: aquasec/trivy:latest
  extends: .base-rules
  needs: ["docker-build"]
  script:
    - trivy image --input image.tar --exit-code 1 --severity HIGH,CRITICAL
  allow_failure: true
""",

    "templates/python.yml": r"""
include:
  - local: '/templates/base.yml'

stages:
  - build
  - test
  - quality
  - package
  - scan

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

# Build Docker image
docker-build:
  stage: package
  extends: 
    - .docker-base
    - .base-rules
  script:
    - docker build -t ${SERVICE_NAME:-$CI_PROJECT_NAME}:$CI_COMMIT_SHORT_SHA .
    - docker save ${SERVICE_NAME:-$CI_PROJECT_NAME}:$CI_COMMIT_SHORT_SHA > image.tar
  artifacts:
    paths:
      - image.tar
    expire_in: 1 hour

# Scan Docker image
scan-image:
  stage: scan
  image: aquasec/trivy:latest
  extends: .base-rules
  needs: ["docker-build"]
  script:
    - trivy image --input image.tar --exit-code 1 --severity HIGH,CRITICAL
  allow_failure: true
""",

    "templates/nodejs.yml": r"""
include:
  - local: '/templates/base.yml'

stages:
  - build
  - test
  - quality
  - package
  - scan

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
    - npm test -- --coverage --coverageReporters=cobertura || true
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

# Security audit
security-scan:
  stage: quality
  image: node:16
  extends: .base-rules
  needs: ["build"]
  script:
    - npm audit --audit-level=moderate || true
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

# Build Docker image
docker-build:
  stage: package
  extends: 
    - .docker-base
    - .base-rules
  script:
    - docker build -t ${SERVICE_NAME:-$CI_PROJECT_NAME}:$CI_COMMIT_SHORT_SHA .
    - docker save ${SERVICE_NAME:-$CI_PROJECT_NAME}:$CI_COMMIT_SHORT_SHA > image.tar
  artifacts:
    paths:
      - image.tar
    expire_in: 1 hour

# Scan Docker image
scan-image:
  stage: scan
  image: aquasec/trivy:latest
  extends: .base-rules
  needs: ["docker-build"]
  script:
    - trivy image --input image.tar --exit-code 1 --severity HIGH,CRITICAL
  allow_failure: true
"""
}

# Project definitions with simple codebases
PROJECTS = {
    # 1. Java Spring Boot - Calculator Service
    "calculator-service": {
        "description": "Java Spring Boot calculator with intentional issues",
        "language": "java",
        "template": "java-maven.yml",
        "files": {
            "src/main/java/com/demo/calculator/CalculatorApplication.java": """
package com.demo.calculator;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class CalculatorApplication {
    public static void main(String[] args) {
        SpringApplication.run(CalculatorApplication.class, args);
    }
}
""",
            "src/main/java/com/demo/calculator/controller/CalculatorController.java": """
package com.demo.calculator.controller;

import org.springframework.web.bind.annotation.*;
import java.util.Map;
import java.util.HashMap;

@RestController
@RequestMapping("/api/calculator")
public class CalculatorController {
    
    // Bug: Division by zero not handled
    @GetMapping("/divide/{a}/{b}")
    public Map<String, Object> divide(@PathVariable double a, @PathVariable double b) {
        Map<String, Object> result = new HashMap<>();
        result.put("result", a / b);  // Will throw ArithmeticException if b is 0
        return result;
    }
    
    // Code smell: Duplicate code
    @GetMapping("/add/{a}/{b}")
    public Map<String, Object> add(@PathVariable double a, @PathVariable double b) {
        Map<String, Object> result = new HashMap<>();
        result.put("operation", "add");
        result.put("a", a);
        result.put("b", b);
        result.put("result", a + b);
        return result;
    }
    
    @GetMapping("/subtract/{a}/{b}")
    public Map<String, Object> subtract(@PathVariable double a, @PathVariable double b) {
        Map<String, Object> result = new HashMap<>();
        result.put("operation", "subtract");
        result.put("a", a);
        result.put("b", b);
        result.put("result", a - b);
        return result;
    }
    
    // Security issue: eval-like behavior
    @PostMapping("/eval")
    public Map<String, Object> evaluate(@RequestBody String expression) {
        // Bad practice: parsing user input as code
        Map<String, Object> result = new HashMap<>();
        result.put("expression", expression);
        result.put("result", "Not implemented - security risk!");
        return result;
    }
}
""",
            "src/test/java/com/demo/calculator/CalculatorApplicationTests.java": """
package com.demo.calculator;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest
class CalculatorApplicationTests {

    @Test
    void contextLoads() {
    }
    
    @Test
    void testAddition() {
        // This test will fail
        assertEquals(5, 2 + 2); // Wrong assertion
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
    <artifactId>calculator-service</artifactId>
    <version>1.0.0</version>
    <packaging>jar</packaging>
    
    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>2.7.0</version>
    </parent>
    
    <properties>
        <java.version>11</java.version>
        <sonar.organization>demo</sonar.organization>
        <sonar.projectKey>calculator-service</sonar.projectKey>
    </properties>
    
    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-web</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-test</artifactId>
            <scope>test</scope>
        </dependency>
    </dependencies>
    
    <build>
        <plugins>
            <plugin>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-maven-plugin</artifactId>
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

    # 2. Python Flask - Todo API
    "todo-api": {
        "description": "Python Flask API with test failures and quality issues",
        "language": "python",
        "template": "python.yml",
        "files": {
            "app.py": """
from flask import Flask, jsonify, request
import json

app = Flask(__name__)

# In-memory storage (not thread-safe)
todos = []

@app.route('/todos', methods=['GET'])
def get_todos():
    return jsonify(todos)

@app.route('/todos', methods=['POST'])
def create_todo():
    data = request.get_json()
    # Bug: No validation
    todo = {
        'id': len(todos) + 1,
        'title': data['title'],  # Will crash if 'title' not provided
        'completed': False
    }
    todos.append(todo)
    return jsonify(todo), 201

@app.route('/todos/<int:todo_id>', methods=['DELETE'])
def delete_todo(todo_id):
    # Bug: No bounds checking
    del todos[todo_id - 1]  # Will crash if todo_id is invalid
    return '', 204

# Security issue: Debug mode enabled
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
""",
            "test_app.py": """
import pytest
from app import app, todos

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client
    todos.clear()

def test_get_todos(client):
    response = client.get('/todos')
    assert response.status_code == 200
    assert response.json == []

def test_create_todo(client):
    response = client.post('/todos', json={'title': 'Test todo'})
    assert response.status_code == 201
    assert response.json['title'] == 'Test todo'

def test_create_todo_without_title(client):
    # This test will fail - the app doesn't handle missing title
    response = client.post('/todos', json={})
    assert response.status_code == 400  # App will actually crash with 500

def test_delete_invalid_todo(client):
    # This test will fail - the app doesn't handle invalid IDs
    response = client.delete('/todos/999')
    assert response.status_code == 404  # App will actually crash with 500
""",
            "requirements.txt": """Flask==2.3.2
pytest==7.4.0
pytest-cov==4.1.0
flake8==6.0.0
bandit==1.7.5
""",
            "Dockerfile": """FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["python", "app.py"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/python.yml'
"""
        }
    },

    # 3. Node.js Express - Weather Service
    "weather-service": {
        "description": "Node.js weather service with quality issues",
        "language": "javascript",
        "template": "nodejs.yml",
        "files": {
            "index.js": """
const express = require('express');
const app = express();
app.use(express.json());

// Hardcoded API key (security issue)
const API_KEY = 'my-secret-weather-api-key';

// In-memory cache (memory leak potential)
const cache = {};

app.get('/weather/:city', async (req, res) => {
    const { city } = req.params;
    
    // Bug: No input validation
    if (cache[city]) {
        return res.json(cache[city]);
    }
    
    // Fake weather data
    const weather = {
        city: city,
        temperature: Math.random() * 30 + 10,
        condition: ['sunny', 'cloudy', 'rainy'][Math.floor(Math.random() * 3)]
    };
    
    // Memory leak: cache grows indefinitely
    cache[city] = weather;
    
    res.json(weather);
});

// Code smell: Duplicate endpoints
app.get('/temperature/:city', async (req, res) => {
    const { city } = req.params;
    const weather = {
        city: city,
        temperature: Math.random() * 30 + 10
    };
    res.json(weather);
});

app.get('/condition/:city', async (req, res) => {
    const { city } = req.params;
    const weather = {
        city: city,
        condition: ['sunny', 'cloudy', 'rainy'][Math.floor(Math.random() * 3)]
    };
    res.json(weather);
});

// Error handling that exposes internals
app.use((err, req, res, next) => {
    res.status(500).json({
        error: err.message,
        stack: err.stack  // Security issue: exposing stack trace
    });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`);
});

module.exports = app;
""",
            "test.js": """
const request = require('supertest');
const app = require('./index');

describe('Weather API', () => {
    test('GET /weather/:city returns weather data', async () => {
        const res = await request(app).get('/weather/London');
        expect(res.statusCode).toBe(200);
        expect(res.body).toHaveProperty('city', 'London');
        expect(res.body).toHaveProperty('temperature');
    });
    
    test('GET /weather/:city validates input', async () => {
        // This test will fail - app doesn't validate input
        const res = await request(app).get('/weather/');
        expect(res.statusCode).toBe(400);
    });
    
    test('Temperature is within valid range', async () => {
        const res = await request(app).get('/weather/TestCity');
        // This might fail randomly due to random temperature
        expect(res.body.temperature).toBeGreaterThan(0);
        expect(res.body.temperature).toBeLessThan(50);
    });
});
""",
            "package.json": """{
  "name": "weather-service",
  "version": "1.0.0",
  "description": "Weather API service",
  "main": "index.js",
  "scripts": {
    "start": "node index.js",
    "test": "jest --coverage",
    "lint": "eslint ."
  },
  "dependencies": {
    "express": "^4.18.2"
  },
  "devDependencies": {
    "jest": "^29.5.0",
    "supertest": "^6.3.3",
    "eslint": "^8.42.0"
  },
  "jest": {
    "testEnvironment": "node",
    "coverageDirectory": "coverage",
    "collectCoverageFrom": [
      "index.js"
    ]
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
  "parserOptions": {
    "ecmaVersion": 12
  },
  "rules": {
    "no-unused-vars": "error",
    "no-console": "warn"
  }
}
""",
            "Dockerfile": """FROM node:16-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .
EXPOSE 3000
CMD ["node", "index.js"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/nodejs.yml'
"""
        }
    },

    # 4. Python FastAPI - User Service (Build Failure)
    "user-service": {
        "description": "Python FastAPI service with missing dependency",
        "language": "python",
        "template": "python.yml",
        "files": {
            "main.py": """
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import bcrypt  # This is not in requirements.txt - will cause build failure

app = FastAPI()

# In-memory user storage
users_db = {}

class User(BaseModel):
    username: str
    email: str
    password: str

class UserResponse(BaseModel):
    username: str
    email: str

@app.post("/users", response_model=UserResponse)
def create_user(user: User):
    # Check if user exists
    if user.username in users_db:
        raise HTTPException(status_code=400, detail="User already exists")
    
    # Hash password (bcrypt not installed - will fail)
    hashed_password = bcrypt.hashpw(user.password.encode('utf-8'), bcrypt.gensalt())
    
    users_db[user.username] = {
        'email': user.email,
        'password': hashed_password
    }
    
    return UserResponse(username=user.username, email=user.email)

@app.get("/users", response_model=List[UserResponse])
def get_users():
    return [
        UserResponse(username=username, email=data['email']) 
        for username, data in users_db.items()
    ]
""",
            "requirements.txt": """fastapi==0.100.0
uvicorn==0.23.1
pydantic==2.0.2
# bcrypt is missing - will cause import error
""",
            "Dockerfile": """FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/python.yml'
"""
        }
    },

    # 5. Java Maven - Library Manager (Test Failure)
    "library-manager": {
        "description": "Java library management with failing tests",
        "language": "java",
        "template": "java-maven.yml",
        "files": {
            "src/main/java/com/demo/library/Book.java": """
package com.demo.library;

public class Book {
    private String isbn;
    private String title;
    private String author;
    private boolean available;
    
    public Book(String isbn, String title, String author) {
        this.isbn = isbn;
        this.title = title;
        this.author = author;
        this.available = true;
    }
    
    // Getters and setters
    public String getIsbn() { return isbn; }
    public String getTitle() { return title; }
    public String getAuthor() { return author; }
    public boolean isAvailable() { return available; }
    public void setAvailable(boolean available) { this.available = available; }
}
""",
            "src/main/java/com/demo/library/Library.java": """
package com.demo.library;

import java.util.*;

public class Library {
    private Map<String, Book> books = new HashMap<>();
    
    public void addBook(Book book) {
        // Bug: No null check
        books.put(book.getIsbn(), book);
    }
    
    public Book borrowBook(String isbn) {
        Book book = books.get(isbn);
        // Bug: No null check
        if (book.isAvailable()) {
            book.setAvailable(false);
            return book;
        }
        throw new RuntimeException("Book not available");
    }
    
    public void returnBook(String isbn) {
        Book book = books.get(isbn);
        // Bug: No null check
        book.setAvailable(true);
    }
    
    public List<Book> getAvailableBooks() {
        List<Book> available = new ArrayList<>();
        for (Book book : books.values()) {
            if (book.isAvailable()) {
                available.add(book);
            }
        }
        return available;
    }
}
""",
            "src/test/java/com/demo/library/LibraryTest.java": """
package com.demo.library;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.BeforeEach;
import static org.junit.jupiter.api.Assertions.*;

public class LibraryTest {
    private Library library;
    
    @BeforeEach
    public void setUp() {
        library = new Library();
    }
    
    @Test
    public void testAddBook() {
        Book book = new Book("123", "Test Book", "Test Author");
        library.addBook(book);
        assertEquals(1, library.getAvailableBooks().size());
    }
    
    @Test
    public void testBorrowBook() {
        Book book = new Book("123", "Test Book", "Test Author");
        library.addBook(book);
        
        Book borrowed = library.borrowBook("123");
        assertFalse(borrowed.isAvailable());
        
        // This will fail - trying to borrow again
        assertThrows(RuntimeException.class, () -> {
            library.borrowBook("123");
        });
    }
    
    @Test
    public void testBorrowNonExistentBook() {
        // This test will fail - app throws NullPointerException instead of proper error
        assertThrows(BookNotFoundException.class, () -> {
            library.borrowBook("999");
        });
    }
    
    @Test
    public void testReturnBook() {
        Book book = new Book("123", "Test Book", "Test Author");
        library.addBook(book);
        library.borrowBook("123");
        
        library.returnBook("123");
        assertTrue(book.isAvailable());
    }
}

class BookNotFoundException extends RuntimeException {}
""",
            "pom.xml": """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 
         https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    
    <groupId>com.demo</groupId>
    <artifactId>library-manager</artifactId>
    <version>1.0.0</version>
    
    <properties>
        <maven.compiler.source>11</maven.compiler.source>
        <maven.compiler.target>11</maven.compiler.target>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
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
        """Create quality gate with reasonable thresholds"""
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
            
        # Add conditions
        conditions = [
            # Coverage
            {'metric': 'new_coverage', 'op': 'LT', 'error': '50'},
            
            # Bugs
            {'metric': 'new_bugs', 'op': 'GT', 'error': '0'},
            
            # Vulnerabilities
            {'metric': 'new_vulnerabilities', 'op': 'GT', 'error': '0'},
            
            # Code Smells
            {'metric': 'new_code_smells', 'op': 'GT', 'error': '5'},
            
            # Duplications
            {'metric': 'new_duplicated_lines_density', 'op': 'GT', 'error': '10'},
            
            # Complexity
            {'metric': 'complexity', 'op': 'GT', 'error': '50'},
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
    print("\n🔵 JAVA PROJECTS:")
    print("  • calculator-service: REST API with division by zero bug and failing tests")
    print("  • library-manager: Library system with null pointer bugs and test failures")
    
    print("\n🟢 PYTHON PROJECTS:")
    print("  • todo-api: Flask API with validation bugs and test failures")
    print("  • user-service: FastAPI with missing dependency (build failure)")
    
    print("\n🟡 JAVASCRIPT PROJECTS:")
    print("  • weather-service: Express API with memory leak and quality issues")
    
    print("\n📚 SHARED PIPELINES:")
    print("  • Templates for Java (Maven), Python, and Node.js projects")
    print("  • Centralized CI/CD configuration")
    print("  • Consistent stages across all projects")
    
    print("\n🔧 CI/CD VARIABLES:")
    print("  • Group-level: Docker, SonarQube, and language defaults")
    print("  • Project-level: Service names, language versions, SonarQube keys")
    
    print("\n🚨 EXPECTED FAILURES:")
    print("  • Build failures: user-service (missing bcrypt dependency)")
    print("  • Test failures: calculator-service, todo-api, library-manager")
    print("  • Quality gate failures: All projects (code smells, coverage)")
    print("  • Security scan failures: Possible in docker images")
    
    print("\n✅ ALL PIPELINES SHOULD RUN WITHOUT CI/CD ERRORS")
    print("   (failures are in the application code, not the pipeline config)")
    print("\n" + "="*80)

if __name__ == "__main__":
    print("=== CI/CD Demo Environment Setup ===\n")
    
    # Get credentials
    gitlab_url = input("GitLab URL [http://localhost:8080]: ").strip() or "http://localhost:8080"
    gitlab_token = getpass.getpass("GitLab Token (with api scope): ")
    sonar_url = input("SonarQube URL [http://localhost:9001]: ").strip() or "http://localhost:9001"
    sonar_token = getpass.getpass("SonarQube Token: ")
    
    print(f"\nThis script will create:")
    print(f"- GitLab group '{GROUP_NAME}'")
    print(f"- Shared pipeline templates repository")
    print(f"- 5 projects with various failure scenarios")
    print(f"- Group and project-level CI/CD variables")
    print(f"- SonarQube quality gate '{QUALITY_GATE_NAME}'")
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