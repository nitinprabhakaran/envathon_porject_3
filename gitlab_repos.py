#!/usr/bin/env python3
"""
Enhanced CI/CD Environment Setup Script - Fixed Version
Creates GitLab projects with various failure scenarios
Focuses on Java, Python, and JavaScript/Node.js projects
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
    {'key': 'CI_REGISTRY', 'value': 'localhost:5000'},  # Local registry or disable
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
    {'key': 'SKIP_IMAGE_PUSH', 'value': 'true'},  # Skip registry push for now
]

# Project-specific variables
PROJECT_VARIABLES = {
    "payment-gateway": [
        {'key': 'SERVICE_NAME', 'value': 'payment-gateway'},
        {'key': 'JAVA_VERSION', 'value': '11'},
        {'key': 'MAVEN_OPTS', 'value': '-Xmx1024m'},
        {'key': 'SONAR_SOURCES', 'value': 'src/main/java'},
        {'key': 'SONAR_JAVA_BINARIES', 'value': 'target/classes'},
    ],
    "user-service": [
        {'key': 'SERVICE_NAME', 'value': 'user-service'},
        {'key': 'PYTHON_VERSION', 'value': '3.9'},
        {'key': 'SONAR_SOURCES', 'value': '.'},
        {'key': 'SONAR_PYTHON_VERSION', 'value': '3.9'},
    ],
    "inventory-api": [
        {'key': 'SERVICE_NAME', 'value': 'inventory-api'},
        {'key': 'NODE_VERSION', 'value': '16'},
        {'key': 'SONAR_SOURCES', 'value': 'src'},
        {'key': 'NPM_CONFIG_CACHE', 'value': '.npm'},
    ],
    "auth-service": [
        {'key': 'SERVICE_NAME', 'value': 'auth-service'},
        {'key': 'JAVA_VERSION', 'value': '11'},
        {'key': 'SONAR_SOURCES', 'value': 'src/main/java'},
        {'key': 'SONAR_JAVA_BINARIES', 'value': 'target/classes'},
    ],
    "notification-api": [
        {'key': 'SERVICE_NAME', 'value': 'notification-api'},
        {'key': 'PYTHON_VERSION', 'value': '3.9'},
        {'key': 'SONAR_SOURCES', 'value': 'src'},
        {'key': 'SONAR_PYTHON_VERSION', 'value': '3.9'},
    ],
    "dashboard-ui": [
        {'key': 'SERVICE_NAME', 'value': 'dashboard-ui'},
        {'key': 'NODE_VERSION', 'value': '16'},
        {'key': 'SONAR_SOURCES', 'value': 'src'},
        {'key': 'BUILD_PATH', 'value': 'build'},
    ],
}

# Enhanced project definitions with various failure scenarios
PROJECTS = {
    # 1. Java Spring Boot - Build failure (missing dependencies)
    "payment-gateway": {
        "description": "Java Spring Boot payment service - Build failure scenario",
        "language": "java",
        "failure_types": ["build", "quality"],
        "files": {
            "src/main/java/com/demo/payment/PaymentGatewayApplication.java": """
package com.demo.payment;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class PaymentGatewayApplication {
    
    public static void main(String[] args) {
        SpringApplication.run(PaymentGatewayApplication.class, args);
    }
}
""",
            "src/main/java/com/demo/payment/controller/PaymentController.java": """
package com.demo.payment.controller;

import com.demo.payment.service.PaymentService;
import com.demo.payment.model.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;
import java.util.*;
import java.sql.*;

@RestController
@RequestMapping("/api/v1/payments")
public class PaymentController {
    
    @Autowired
    private PaymentService paymentService;
    
    // Security vulnerability: SQL injection
    @PostMapping("/process")
    public PaymentResponse processPayment(@RequestBody PaymentRequest request) {
        String query = "SELECT * FROM payments WHERE user_id = '" + request.getUserId() + "'";
        // Bad practice: executing raw SQL
        
        // Bug: No validation
        double amount = request.getAmount();
        
        // Code smell: Magic numbers
        if (amount > 10000) {
            throw new RuntimeException("Amount too large");
        }
        
        return paymentService.processPayment(request);
    }
    
    // Duplicate code (code smell)
    @GetMapping("/status/{id}")
    public Map<String, Object> getPaymentStatus(@PathVariable String id) {
        Map<String, Object> result = new HashMap<>();
        
        // Hardcoded values
        Connection conn = null;
        try {
            conn = DriverManager.getConnection("jdbc:mysql://localhost:3306/payments", "root", "password");
            // Security issue: credentials in code
        } catch (SQLException e) {
            // Swallowing exception
        }
        
        result.put("status", "SUCCESS");
        result.put("id", id);
        return result;
    }
}
""",
            "src/main/java/com/demo/payment/model/PaymentRequest.java": """
package com.demo.payment.model;

public class PaymentRequest {
    private String userId;
    private String cardNumber;
    private double amount;
    private String currency;
    
    public String getUserId() { return userId; }
    public void setUserId(String userId) { this.userId = userId; }
    
    public String getCardNumber() { return cardNumber; }
    public void setCardNumber(String cardNumber) { this.cardNumber = cardNumber; }
    
    public double getAmount() { return amount; }
    public void setAmount(double amount) { this.amount = amount; }
    
    public String getCurrency() { return currency; }
    public void setCurrency(String currency) { this.currency = currency; }
}
""",
            "src/main/java/com/demo/payment/model/PaymentResponse.java": """
package com.demo.payment.model;

public class PaymentResponse {
    private String transactionId;
    private String status;
    
    public PaymentResponse(String transactionId, String status) {
        this.transactionId = transactionId;
        this.status = status;
    }
    
    public String getTransactionId() { return transactionId; }
    public String getStatus() { return status; }
}
""",
            "src/main/java/com/demo/payment/model/Payment.java": """
package com.demo.payment.model;

import javax.persistence.*;

@Entity
@Table(name = "payments")
public class Payment {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    private String userId;
    private String merchantId;
    private Double amount;
    private String currency;
    private String status;
    
    // Getters and setters
    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    
    public String getUserId() { return userId; }
    public void setUserId(String userId) { this.userId = userId; }
    
    public String getMerchantId() { return merchantId; }
    public void setMerchantId(String merchantId) { this.merchantId = merchantId; }
    
    public Double getAmount() { return amount; }
    public void setAmount(Double amount) { this.amount = amount; }
    
    public String getCurrency() { return currency; }
    public void setCurrency(String currency) { this.currency = currency; }
    
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
}
""",
            "src/main/java/com/demo/payment/service/PaymentService.java": """
package com.demo.payment.service;

import com.demo.payment.model.*;
import com.demo.payment.repository.PaymentRepository;
import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Autowired;
import java.util.*;
import javax.crypto.Cipher;
import javax.crypto.spec.SecretKeySpec;

@Service
public class PaymentService {
    
    @Autowired
    private PaymentRepository repository;
    
    // Vulnerability: Weak encryption
    private static final String ENCRYPTION_KEY = "1234567890123456";
    
    public PaymentResponse processPayment(PaymentRequest request) {
        // Bug: No null checks
        String cardNumber = request.getCardNumber();
        
        // Security issue: Logging sensitive data
        System.out.println("Processing payment for card: " + cardNumber);
        
        // Vulnerability: Weak random number generator
        Random random = new Random();
        String transactionId = String.valueOf(random.nextInt(999999));
        
        try {
            // Vulnerability: ECB mode encryption
            Cipher cipher = Cipher.getInstance("AES/ECB/NoPadding");
            SecretKeySpec key = new SecretKeySpec(ENCRYPTION_KEY.getBytes(), "AES");
            cipher.init(Cipher.ENCRYPT_MODE, key);
            
            // Store encrypted card number (bad practice)
            byte[] encrypted = cipher.doFinal(cardNumber.getBytes());
            
        } catch (Exception e) {
            // Generic exception handling
            e.printStackTrace();
        }
        
        return new PaymentResponse(transactionId, "SUCCESS");
    }
}
""",
            "src/main/java/com/demo/payment/repository/PaymentRepository.java": """
package com.demo.payment.repository;

import com.demo.payment.model.Payment;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import java.util.List;

public interface PaymentRepository extends JpaRepository<Payment, Long> {
    
    // Vulnerability: SQL injection in native query
    @Query(value = "SELECT * FROM payments WHERE user_id = ?1", nativeQuery = true)
    List<Payment> findByUserId(String userId);
    
    @Query(value = "SELECT * FROM transactions WHERE payment_id = ?1", nativeQuery = true)
    List<Object[]> findRelatedTransactions(Long paymentId);
    
    List<Payment> findAll();
}
""",
            "pom.xml": """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 
         https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    
    <groupId>com.demo</groupId>
    <artifactId>payment-gateway</artifactId>
    <version>1.0.0</version>
    <packaging>jar</packaging>
    
    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>2.7.0</version>
    </parent>
    
    <properties>
        <java.version>11</java.version>
    </properties>
    
    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-web</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-data-jpa</artifactId>
        </dependency>
        <!-- Missing H2 database dependency - will cause build failure -->
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-test</artifactId>
            <scope>test</scope>
        </dependency>
        <!-- Vulnerable dependency -->
        <dependency>
            <groupId>commons-collections</groupId>
            <artifactId>commons-collections</artifactId>
            <version>3.2.1</version>
        </dependency>
    </dependencies>
</project>
""",
            "Dockerfile": """FROM openjdk:11-jre-slim
WORKDIR /app
COPY target/*.jar app.jar

# Security issue: Running as root
EXPOSE 8080

# Hardcoded environment variables
ENV DB_HOST=localhost
ENV DB_PASSWORD=password

CMD ["java", "-jar", "app.jar"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/java-complete.yml'
"""
        }
    },

    # 2. Python FastAPI - Fixed dependencies
    "user-service": {
        "description": "Python FastAPI user service - Test failures & quality issues",
        "language": "python",
        "failure_types": ["test", "quality", "security"],
        "files": {
            "app/main.py": """
from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy import create_engine, text
from typing import Optional, List
import jwt
import hashlib
import pickle
import yaml
import os

app = FastAPI(title="User Management Service")

# Security issue: Hardcoded secret
JWT_SECRET = "super_secret_key_123"
DATABASE_URL = "postgresql://user:password@localhost/users"

# Vulnerability: SQL injection
@app.get("/users/{user_id}")
async def get_user(user_id: str):
    # Direct string concatenation in SQL
    query = f"SELECT * FROM users WHERE id = '{user_id}'"
    
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        result = conn.execute(text(query))
        user = result.fetchone()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {"user": dict(user)}

# Bug: Race condition
user_sessions = {}

@app.post("/login")
async def login(username: str, password: str):
    # Vulnerability: Weak hashing
    password_hash = hashlib.md5(password.encode()).hexdigest()
    
    # Hardcoded admin credentials
    if username == "admin" and password == "admin123":
        token = jwt.encode({"user": "admin"}, JWT_SECRET, algorithm="HS256")
        user_sessions[username] = token  # Race condition here
        return {"token": token}
    
    # SQL injection vulnerability
    query = f"SELECT * FROM users WHERE username='{username}' AND password_hash='{password_hash}'"
    # Execute query...
    
    return {"status": "login failed"}

# Code smell: Duplicate code
@app.get("/admin/users")
async def get_admin_users():
    query = "SELECT * FROM users WHERE role='admin'"
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        result = conn.execute(text(query))
        users = result.fetchall()
    return {"users": [dict(u) for u in users]}

@app.get("/manager/users")
async def get_manager_users():
    # Duplicate logic
    query = "SELECT * FROM users WHERE role='manager'"
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        result = conn.execute(text(query))
        users = result.fetchall()
    return {"users": [dict(u) for u in users]}

# Vulnerability: Path traversal
@app.get("/files/{filename}")
async def get_file(filename: str):
    # No path validation
    with open(f"/app/data/{filename}", "r") as f:
        content = f.read()
    return {"content": content}

# Performance issue: N+1 queries
@app.get("/users/detailed")
async def get_users_detailed():
    users = []  # Get all users first
    
    # Then for each user, fetch additional data
    for user in users:
        # Individual query for each user's profile
        profile = fetch_user_profile(user['id'])
        # Another query for user's settings
        settings = fetch_user_settings(user['id'])
        user['profile'] = profile
        user['settings'] = settings
    
    return {"users": users}

def fetch_user_profile(user_id):
    # Simulated database call
    pass

def fetch_user_settings(user_id):
    # Simulated database call
    pass
""",
            "app/models.py": """
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(50))  # No unique constraint
    email = Column(String(100))
    password_hash = Column(String(32))  # MD5 hash - insecure
    role = Column(String(20))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Bug: No validation
    # Missing indexes
""",
            "tests/test_users.py": """
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_get_user():
    # This test will fail - SQL injection protection will break it
    response = client.get("/users/1' OR '1'='1")
    assert response.status_code == 200  # Will actually be 500

def test_login():
    # Test will fail due to hardcoded credentials
    response = client.post("/login", json={
        "username": "testuser",
        "password": "testpass"
    })
    assert response.status_code == 200
    assert "token" in response.json()  # Will fail

def test_admin_access():
    # Missing authentication
    response = client.get("/admin/users")
    assert response.status_code == 401  # Will fail - no auth check

# Test that passes
def test_health():
    response = client.get("/")
    assert response.status_code == 200
""",
            "requirements.txt": """fastapi==0.104.1
uvicorn==0.24.0
sqlalchemy==1.4.32
pytest==7.4.3
pytest-asyncio==0.21.1
httpx==0.25.2
pyjwt==2.8.0
psycopg2-binary==2.9.9
pyyaml==6.0.1
# No conflicting packages
""",
            "Dockerfile": """FROM python:3.9-slim

WORKDIR /app

# Security issue: Running as root
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Exposing unnecessary ports
EXPOSE 8000 8001 8002

# Hardcoded secrets in environment
ENV JWT_SECRET=super_secret_key_123
ENV DATABASE_URL=postgresql://user:password@localhost/users

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/python-complete.yml'
"""
        }
    },

    # 3. Node.js Express - Fixed test hanging issue
    "inventory-api": {
        "description": "Node.js inventory API - Quality gate failures",
        "language": "nodejs",
        "failure_types": ["quality", "security"],
        "files": {
            "src/app.js": r"""
const express = require('express');
const mongoose = require('mongoose');
const bodyParser = require('body-parser');
const jwt = require('jsonwebtoken');
const bcrypt = require('bcrypt');
const fs = require('fs');
const path = require('path');

const app = express();
app.use(bodyParser.json());

// Models
const Inventory = require('./models/Inventory');
const User = require('./models/User');

// Security issue: Hardcoded connection string
const mongoUrl = 'mongodb://admin:password@localhost:27017/inventory';

// Vulnerability: No input validation
app.post('/api/inventory/search', (req, res) => {
    const { query } = req.body;
    
    // NoSQL injection vulnerability
    Inventory.find({ $where: `this.name == '${query}'` }, (err, items) => {
        if (err) {
            console.error(err);  // Information disclosure
            return res.status(500).json({ error: err.message });
        }
        res.json(items);
    });
});

// Duplicate code blocks
app.post('/api/inventory/add', async (req, res) => {
    const { name, quantity, price } = req.body;
    
    // No validation
    const item = new Inventory({
        name: name,
        quantity: quantity,
        price: price,
        created: new Date()
    });
    
    try {
        await item.save();
        
        // Duplicate logging logic
        console.log(`Item added: ${name}`);
        fs.appendFileSync('inventory.log', `[${new Date()}] Item added: ${name}\n`);
        
        res.json({ success: true });
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

app.post('/api/inventory/update', async (req, res) => {
    const { id, name, quantity, price } = req.body;
    
    // Duplicate validation logic
    const item = await Inventory.findById(id);
    item.name = name;
    item.quantity = quantity;
    item.price = price;
    
    try {
        await item.save();
        
        // Duplicate logging logic (same as above)
        console.log(`Item updated: ${name}`);
        fs.appendFileSync('inventory.log', `[${new Date()}] Item updated: ${name}\n`);
        
        res.json({ success: true });
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

// Security vulnerability: JWT with weak secret
const JWT_SECRET = 'secret123';

app.post('/api/auth/login', async (req, res) => {
    const { username, password } = req.body;
    
    // SQL-like injection in MongoDB
    const user = await User.findOne({ username: username });
    
    // Timing attack vulnerability
    if (user && user.password === password) {
        const token = jwt.sign({ username }, JWT_SECRET);
        res.json({ token });
    } else {
        res.status(401).json({ error: 'Invalid credentials' });
    }
});

// Memory leak
let cache = {};
app.get('/api/inventory/:id', async (req, res) => {
    const { id } = req.params;
    
    // Cache never cleared - memory leak
    if (!cache[id]) {
        cache[id] = await Inventory.findById(id);
    }
    
    res.json(cache[id]);
});

// Global error handler that leaks information
app.use((err, req, res, next) => {
    console.error(err.stack);  // Full stack trace
    res.status(500).json({
        error: err.message,
        stack: err.stack  // Security issue: exposing stack trace
    });
});

// Export for testing
module.exports = app;
""",
            "src/server.js": """
const app = require('./app');
const mongoose = require('mongoose');

const PORT = process.env.PORT || 3000;
const mongoUrl = 'mongodb://admin:password@localhost:27017/inventory';

// Connect to MongoDB
mongoose.connect(mongoUrl, {
    useNewUrlParser: true,
    useUnifiedTopology: true
}).then(() => {
    console.log('Connected to MongoDB');
    app.listen(PORT, () => {
        console.log(`Server running on port ${PORT}`);
    });
}).catch(err => {
    console.error('MongoDB connection error:', err);
    process.exit(1);
});
""",
            "src/models/Inventory.js": """
const mongoose = require('mongoose');

// Poor schema design
const inventorySchema = new mongoose.Schema({
    name: String,  // No validation
    quantity: Number,  // Can be negative
    price: Number,  // No decimal precision
    categoryId: String,  // Should be ObjectId
    supplierId: String,  // Should be ObjectId
    warehouseId: String,  // Should be ObjectId
    created: Date,
    
    // Security issue: storing sensitive data
    internalNotes: String,  // Might contain passwords
    
    // Performance issue: large embedded documents
    history: [{
        date: Date,
        action: String,
        user: String,
        details: Object  // Unbounded growth
    }]
});

// No indexes defined - performance issue

module.exports = mongoose.model('Inventory', inventorySchema);
""",
            "src/models/User.js": """
const mongoose = require('mongoose');

const userSchema = new mongoose.Schema({
    username: String,
    password: String,  // Storing plain text password!
    email: String,
    role: String
});

module.exports = mongoose.model('User', userSchema);
""",
            "tests/inventory.test.js": """
const request = require('supertest');
const app = require('../src/app');

// Mock mongoose to prevent connection issues during tests
jest.mock('mongoose', () => ({
    connect: jest.fn().mockResolvedValue(true),
    model: jest.fn().mockReturnValue({
        findById: jest.fn(),
        findOne: jest.fn(),
        find: jest.fn()
    }),
    Schema: jest.fn().mockImplementation(() => ({}))
}));

describe('Inventory API', () => {
    afterAll((done) => {
        // Ensure Jest exits properly
        done();
    });
    
    test('GET /api/inventory/:id', async () => {
        const res = await request(app).get('/api/inventory/123');
        expect(res.statusCode).toBe(200);
    });
    
    test('POST /api/inventory/add', async () => {
        const res = await request(app)
            .post('/api/inventory/add')
            .send({
                name: 'Test Item',
                quantity: 10,
                price: 99.99
            });
        expect(res.statusCode).toBe(200);
    });
});
""",
            "package.json": """{
  "name": "inventory-api",
  "version": "1.0.0",
  "description": "Inventory management API",
  "main": "src/server.js",
  "scripts": {
    "start": "node src/server.js",
    "test": "jest --coverage --forceExit --detectOpenHandles",
    "lint": "eslint src/"
  },
  "dependencies": {
    "express": "4.17.1",
    "mongoose": "5.11.15",
    "jsonwebtoken": "8.5.1",
    "bcrypt": "5.0.0",
    "body-parser": "1.19.0",
    "morgan": "1.10.0"
  },
  "devDependencies": {
    "jest": "27.0.6",
    "supertest": "6.1.3",
    "eslint": "7.32.0"
  },
  "jest": {
    "testEnvironment": "node",
    "testTimeout": 10000
  }
}
""",
            "Dockerfile": """FROM node:16-alpine

WORKDIR /app

# Inefficient layering
COPY . .
RUN npm install

# Security: Running as root
EXPOSE 3000

# No health check defined
CMD ["npm", "start"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/nodejs-complete.yml'
"""
        }
    },

    # 4. Java Spring Boot - Authentication service
    "auth-service": {
        "description": "Java Spring Boot auth service - Security vulnerabilities",
        "language": "java",
        "failure_types": ["security", "quality"],
        "files": {
            "src/main/java/com/demo/auth/AuthServiceApplication.java": """
package com.demo.auth;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class AuthServiceApplication {
    
    public static void main(String[] args) {
        SpringApplication.run(AuthServiceApplication.class, args);
    }
}
""",
            "src/main/java/com/demo/auth/controller/AuthController.java": """
package com.demo.auth.controller;

import com.demo.auth.service.AuthService;
import com.demo.auth.model.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;
import java.util.*;
import java.security.MessageDigest;

@RestController
@RequestMapping("/api/auth")
public class AuthController {
    
    @Autowired
    private AuthService authService;
    
    // Hardcoded secret key
    private static final String SECRET_KEY = "my-secret-key-123";
    
    @PostMapping("/login")
    public LoginResponse login(@RequestBody LoginRequest request) {
        // Vulnerability: Timing attack
        if (request.getUsername().equals("admin") && 
            request.getPassword().equals("admin123")) {
            return new LoginResponse("admin-token", "admin");
        }
        
        // SQL injection via string concatenation
        String query = "SELECT * FROM users WHERE username = '" + 
                      request.getUsername() + "' AND password = '" + 
                      request.getPassword() + "'";
        
        // Weak hashing
        try {
            MessageDigest md = MessageDigest.getInstance("MD5");
            byte[] hash = md.digest(request.getPassword().getBytes());
            // Use weak hash...
        } catch (Exception e) {
            e.printStackTrace();
        }
        
        return authService.authenticate(request);
    }
    
    @GetMapping("/users")
    public List<User> getAllUsers() {
        // No authentication check
        return authService.getAllUsers();
    }
    
    @PostMapping("/register")
    public User register(@RequestBody User user) {
        // Mass assignment vulnerability
        // User can set any field including role
        return authService.createUser(user);
    }
    
    // Information disclosure
    @GetMapping("/config")
    public Map<String, String> getConfig() {
        Map<String, String> config = new HashMap<>();
        config.put("database_url", "jdbc:mysql://localhost:3306/auth");
        config.put("database_user", "root");
        config.put("database_password", "password123");
        config.put("jwt_secret", SECRET_KEY);
        return config;
    }
}
""",
            "src/main/java/com/demo/auth/model/User.java": """
package com.demo.auth.model;

import javax.persistence.*;

@Entity
@Table(name = "users")
public class User {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    private String username;
    private String password;  // Storing plain text!
    private String email;
    private String role;
    
    // No validation annotations
    
    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    
    public String getUsername() { return username; }
    public void setUsername(String username) { this.username = username; }
    
    public String getPassword() { return password; }
    public void setPassword(String password) { this.password = password; }
    
    public String getEmail() { return email; }
    public void setEmail(String email) { this.email = email; }
    
    public String getRole() { return role; }
    public void setRole(String role) { this.role = role; }
}
""",
            "src/main/java/com/demo/auth/model/LoginRequest.java": """
package com.demo.auth.model;

public class LoginRequest {
    private String username;
    private String password;
    
    public String getUsername() { return username; }
    public void setUsername(String username) { this.username = username; }
    
    public String getPassword() { return password; }
    public void setPassword(String password) { this.password = password; }
}
""",
            "src/main/java/com/demo/auth/model/LoginResponse.java": """
package com.demo.auth.model;

public class LoginResponse {
    private String token;
    private String username;
    
    public LoginResponse(String token, String username) {
        this.token = token;
        this.username = username;
    }
    
    public String getToken() { return token; }
    public String getUsername() { return username; }
}
""",
            "src/main/java/com/demo/auth/service/AuthService.java": """
package com.demo.auth.service;

import com.demo.auth.model.*;
import com.demo.auth.repository.UserRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import java.util.*;

@Service
public class AuthService {
    
    @Autowired
    private UserRepository userRepository;
    
    // Weak token generation
    public LoginResponse authenticate(LoginRequest request) {
        User user = userRepository.findByUsername(request.getUsername());
        
        if (user != null && user.getPassword().equals(request.getPassword())) {
            // Simple predictable token
            String token = Base64.getEncoder().encodeToString(
                (user.getUsername() + ":" + System.currentTimeMillis()).getBytes()
            );
            return new LoginResponse(token, user.getUsername());
        }
        
        return null;
    }
    
    public List<User> getAllUsers() {
        // Exposing all user data including passwords
        return userRepository.findAll();
    }
    
    public User createUser(User user) {
        // No password hashing
        // No validation
        return userRepository.save(user);
    }
}
""",
            "src/main/java/com/demo/auth/repository/UserRepository.java": """
package com.demo.auth.repository;

import com.demo.auth.model.User;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

public interface UserRepository extends JpaRepository<User, Long> {
    
    // SQL injection prone
    @Query(value = "SELECT * FROM users WHERE username = ?1", nativeQuery = true)
    User findByUsername(String username);
}
""",
            "pom.xml": """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 
         https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    
    <groupId>com.demo</groupId>
    <artifactId>auth-service</artifactId>
    <version>1.0.0</version>
    <packaging>jar</packaging>
    
    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>2.7.0</version>
    </parent>
    
    <properties>
        <java.version>11</java.version>
    </properties>
    
    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-web</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-data-jpa</artifactId>
        </dependency>
        <dependency>
            <groupId>com.h2database</groupId>
            <artifactId>h2</artifactId>
            <scope>runtime</scope>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-test</artifactId>
            <scope>test</scope>
        </dependency>
        <!-- Old vulnerable dependency -->
        <dependency>
            <groupId>org.apache.logging.log4j</groupId>
            <artifactId>log4j-core</artifactId>
            <version>2.14.0</version>
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

# Running as root
EXPOSE 8080

# Hardcoded secrets
ENV DB_PASSWORD=password123
ENV JWT_SECRET=my-secret-key-123

CMD ["java", "-jar", "app.jar"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/java-complete.yml'
"""
        }
    },

    # 5. Python Django - Notification API
    "notification-api": {
        "description": "Python Django notification API - Performance and security issues",
        "language": "python",
        "failure_types": ["quality", "performance"],
        "files": {
            "src/manage.py": """#!/usr/bin/env python
import os
import sys

if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'notification.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)
""",
            "src/notification/__init__.py": "",
            "src/notification/settings.py": """
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Security issue: Hardcoded secret key
SECRET_KEY = 'django-insecure-1234567890abcdefghijklmnop'

# Security issue: Debug enabled
DEBUG = True

ALLOWED_HOSTS = ['*']  # Security issue

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'api',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    # Missing CSRF middleware - security issue
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'notification.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'notification.wsgi.application'

# Database - hardcoded credentials
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}

# No password validators - security issue
AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True

STATIC_URL = '/static/'
""",
            "src/notification/urls.py": """
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
]
""",
            "src/notification/wsgi.py": """
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'notification.settings')
application = get_wsgi_application()
""",
            "src/api/__init__.py": "",
            "src/api/models.py": """
from django.db import models
from django.contrib.auth.models import User

class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(default=False)
    
    # No indexes defined
    # No validation
    
class EmailTemplate(models.Model):
    name = models.CharField(max_length=100)
    subject = models.CharField(max_length=200)
    body = models.TextField()  # Stores raw HTML - XSS risk
    
    # No sanitization
""",
            "src/api/views.py": """
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.models import User
from .models import Notification, EmailTemplate
import json
import os

# No authentication required - security issue
@csrf_exempt
def send_notification(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        
        # Mass assignment vulnerability
        notification = Notification.objects.create(**data)
        
        # Performance issue: N+1 queries
        users = User.objects.all()
        for user in users:
            # Individual query for each user
            user_notifications = Notification.objects.filter(user=user)
            # Process notifications...
        
        return JsonResponse({'status': 'sent', 'id': notification.id})
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)

# SQL injection via raw query
def get_user_notifications(request, username):
    # Vulnerable to SQL injection
    query = f"SELECT * FROM api_notification WHERE user_id IN (SELECT id FROM auth_user WHERE username = '{username}')"
    
    # Using raw SQL
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute(query)
        results = cursor.fetchall()
    
    return JsonResponse({'notifications': results})

# Template injection vulnerability
@csrf_exempt
def render_template(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        template_body = data.get('template', '')
        context = data.get('context', {})
        
        # Dangerous: User input in template
        from django.template import Template, Context
        template = Template(template_body)
        rendered = template.render(Context(context))
        
        return JsonResponse({'rendered': rendered})
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)

# File operation vulnerability
def export_notifications(request):
    filename = request.GET.get('filename', 'export.json')
    
    # Path traversal vulnerability
    filepath = os.path.join('/tmp', filename)
    
    notifications = list(Notification.objects.all().values())
    
    # Blocking I/O
    with open(filepath, 'w') as f:
        json.dump(notifications, f)
    
    return JsonResponse({'file': filepath})

# Performance issue: Loading all data
def get_all_notifications(request):
    # Loading entire table into memory
    notifications = list(Notification.objects.all().values())
    
    # No pagination
    return JsonResponse({'notifications': notifications, 'count': len(notifications)})
""",
            "src/api/urls.py": """
from django.urls import path
from . import views

urlpatterns = [
    path('send/', views.send_notification),
    path('user/<str:username>/', views.get_user_notifications),
    path('template/', views.render_template),
    path('export/', views.export_notifications),
    path('all/', views.get_all_notifications),
]
""",
            "tests/test_api.py": """
import pytest
from django.test import TestCase, Client
from django.contrib.auth.models import User
from api.models import Notification

class NotificationAPITest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
    
    def test_send_notification(self):
        # This test will pass but doesn't check security
        response = self.client.post('/api/send/', 
            data={'user': self.user.id, 'message': 'Test notification'},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
    
    def test_get_notifications(self):
        # SQL injection not tested
        response = self.client.get(f'/api/user/{self.user.username}/')
        self.assertEqual(response.status_code, 200)
    
    def test_template_rendering(self):
        # Template injection not tested
        response = self.client.post('/api/template/',
            data={'template': 'Hello {{ name }}', 'context': {'name': 'World'}},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
""",
            "requirements.txt": """Django==3.2.13
djangorestframework==3.13.1
psycopg2-binary==2.9.3
gunicorn==20.1.0
pytest==7.1.2
pytest-django==4.5.2
# Vulnerable dependency
Pillow==8.1.1
""",
            "Dockerfile": """FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ .

# Running as root
EXPOSE 8000

# Hardcoded environment
ENV DJANGO_SETTINGS_MODULE=notification.settings
ENV PYTHONUNBUFFERED=1

# No static file collection
CMD ["gunicorn", "notification.wsgi:application", "--bind", "0.0.0.0:8000"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/python-complete.yml'
"""
        }
    },

    # 6. React Dashboard - Frontend with quality issues
    "dashboard-ui": {
        "description": "React dashboard UI - Build and quality issues",
        "language": "javascript",
        "failure_types": ["quality", "security"],
        "files": {
            "src/App.js": r"""import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

// Hardcoded API configuration
const API_KEY = 'sk_live_1234567890abcdef';
const API_URL = 'https://api.example.com';

function App() {
  const [user, setUser] = useState(null);
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  
  // Performance issue: Missing dependency array
  useEffect(() => {
    fetchUserData();
    fetchDashboardData();
  });
  
  // Security: Storing sensitive data
  const fetchUserData = async () => {
    try {
      const response = await axios.get(`${API_URL}/user`, {
        headers: { 'X-API-Key': API_KEY }
      });
      
      // Storing sensitive data in localStorage
      localStorage.setItem('user_token', response.data.token);
      localStorage.setItem('api_key', API_KEY);
      
      setUser(response.data);
    } catch (error) {
      console.error('Full error:', error); // Information disclosure
    }
  };
  
  // Performance: No pagination
  const fetchDashboardData = async () => {
    const response = await axios.get(`${API_URL}/dashboard/all`);
    setData(response.data); // Could be huge dataset
  };
  
  // XSS vulnerability
  const renderUserContent = (content) => {
    return <div dangerouslySetInnerHTML={{ __html: content }} />;
  };
  
  // Memory leak: Event listener
  useEffect(() => {
    const handleScroll = () => console.log('Scrolling');
    window.addEventListener('scroll', handleScroll);
    // Missing cleanup
  }, []);
  
  return (
    <div className="App">
      <header>
        <h1>Dashboard</h1>
        {/* Exposing API key in UI */}
        <div className="api-status">API Key: {API_KEY}</div>
      </header>
      
      {user && (
        <div className="user-section">
          {/* XSS vulnerability */}
          {renderUserContent(user.bio)}
        </div>
      )}
      
      {/* Performance: Rendering large lists */}
      <div className="data-grid">
        {data.map((item, index) => (
          <div key={index} className="data-item">
            <h3>{item.title}</h3>
            <p>{item.description}</p>
            {/* Rendering user HTML */}
            <div dangerouslySetInnerHTML={{ __html: item.content }} />
          </div>
        ))}
      </div>
    </div>
  );
}

// Duplicate components
function Card({ title, content }) {
  return (
    <div className="card">
      <h3>{title}</h3>
      <p>{content}</p>
    </div>
  );
}

function CardWithImage({ title, content, image }) {
  return (
    <div className="card">
      <img src={image} alt={title} />
      <h3>{title}</h3>
      <p>{content}</p>
    </div>
  );
}

export default App;
""",
            "src/components/Login.js": r"""import React, { useState } from 'react';
import axios from 'axios';

const Login = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  
  const handleLogin = async (e) => {
    e.preventDefault();
    
    // Client-side validation only
    if (username === 'admin' && password === 'admin') {
      localStorage.setItem('isAdmin', 'true');
      window.location.href = '/admin';
      return;
    }
    
    // Logging credentials
    console.log('Login attempt:', { username, password });
    
    try {
      // Sending credentials over HTTP
      const response = await axios.post('http://api.example.com/login', {
        username,
        password
      });
      
      // Weak token storage
      document.cookie = `token=${response.data.token}`;
      localStorage.setItem('token', response.data.token);
      
    } catch (error) {
      // Exposing error details
      alert(`Login failed: ${error.response.data.message}`);
    }
  };
  
  return (
    <form onSubmit={handleLogin}>
      <input
        type="text"
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        placeholder="Username"
        autoComplete="username"
      />
      <input
        type="text" // Should be password type
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Password"
      />
      <button type="submit">Login</button>
    </form>
  );
};

// Duplicate login form
const LoginForm = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  
  // Same implementation as above...
  
  return (
    <form>
      {/* Duplicate code */}
    </form>
  );
};

export default Login;
""",
            "src/utils/api.js": r"""import axios from 'axios';

// Hardcoded configuration
const API_BASE = 'http://api.example.com';
const API_KEY = 'sk_live_1234567890';

// Creating axios instance with exposed key
const apiClient = axios.create({
  baseURL: API_BASE,
  headers: {
    'X-API-Key': API_KEY,
    'Content-Type': 'application/json'
  }
});

// No request/response interceptors for error handling

// Duplicate API calls
export const fetchUsers = async () => {
  const response = await apiClient.get('/users');
  return response.data;
};

export const getUsers = async () => {
  // Duplicate of fetchUsers
  const response = await apiClient.get('/users');
  return response.data;
};

// No error handling
export const createUser = async (userData) => {
  const response = await apiClient.post('/users', userData);
  return response.data;
};

// Exposing internal API structure
export const debugAPI = () => {
  console.log('API Configuration:', {
    base: API_BASE,
    key: API_KEY,
    endpoints: ['/users', '/admin', '/config']
  });
};

export default apiClient;
""",
            "package.json": """{
  "name": "dashboard-ui",
  "version": "1.0.0",
  "dependencies": {
    "react": "17.0.2",
    "react-dom": "17.0.2",
    "axios": "0.21.1",
    "react-router-dom": "5.2.0",
    "lodash": "4.17.19",
    "moment": "2.29.1"
  },
  "devDependencies": {
    "react-scripts": "4.0.3",
    "@testing-library/react": "11.2.7",
    "@testing-library/jest-dom": "5.14.1"
  },
  "scripts": {
    "start": "react-scripts start",
    "build": "react-scripts build",
    "test": "react-scripts test --watchAll=false",
    "eject": "react-scripts eject"
  },
  "eslintConfig": {
    "extends": ["react-app"]
  },
  "browserslist": {
    "production": [">0.2%", "not dead", "not op_mini all"],
    "development": ["last 1 chrome version", "last 1 firefox version"]
  }
}
""",
            "public/index.html": """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Dashboard</title>
    <!-- Exposing internal info -->
    <meta name="api-endpoint" content="https://api.example.com" />
    <meta name="version" content="1.0.0-internal" />
  </head>
  <body>
    <noscript>You need to enable JavaScript to run this app.</noscript>
    <div id="root"></div>
    <!-- Including API key in HTML -->
    <script>
      window.API_KEY = 'sk_live_1234567890';
      window.DEBUG_MODE = true;
    </script>
  </body>
</html>
""",
            "src/App.css": """/* Basic styles */
.App {
  text-align: center;
  padding: 20px;
}

.api-status {
  background: #f0f0f0;
  padding: 10px;
  margin: 10px;
  /* Exposing sensitive info in CSS */
  /* API endpoint: https://api.example.com */
}

.data-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 20px;
  margin: 20px;
}

.card {
  border: 1px solid #ddd;
  padding: 15px;
  border-radius: 8px;
}

/* Duplicate styles */
.data-item {
  border: 1px solid #ddd;
  padding: 15px;
  border-radius: 8px;
}
""",
            "src/App.test.js": """import { render, screen } from '@testing-library/react';
import App from './App';

test('renders dashboard header', () => {
  render(<App />);
  const headerElement = screen.getByText(/Dashboard/i);
  expect(headerElement).toBeInTheDocument();
});

// Missing security tests
// Missing performance tests
// Missing error handling tests
""",
            "Dockerfile": """FROM node:16-alpine AS build

WORKDIR /app

# Copying everything including secrets
COPY . .
RUN npm install
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html

# No custom nginx config
# No security headers
# Running as root

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/react-complete.yml'
"""
        }
    }
}

# Continuing from Part 1...

# Enhanced shared CI/CD templates
SHARED_TEMPLATES = {
    "templates/base.yml": """
# Base template with all stages
variables:
  DOCKER_DRIVER: overlay2
  DOCKER_TLS_CERTDIR: ""
  SONAR_USER_HOME: "${CI_PROJECT_DIR}/.sonar"
  GIT_DEPTH: "0"
  IMAGE_NAME: "${CI_PROJECT_NAME}"
  IMAGE_TAG: "${CI_PROJECT_NAME}:${CI_COMMIT_SHORT_SHA}"

stages:
  - build
  - test
  - scan
  - package
  - security-scan
  - deploy
  - cleanup

# Base job templates
.base-rules:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'

.docker-base:
  image: docker:24.0.5
  services:
    - docker:24.0.5-dind
  before_script:
    - docker info
    - |
      if [ "$SKIP_IMAGE_PUSH" != "true" ] && [ -n "$CI_REGISTRY" ]; then
        echo "Logging in to registry $CI_REGISTRY"
        echo "$CI_JOB_TOKEN" | docker login -u gitlab-ci-token --password-stdin $CI_REGISTRY || true
      else
        echo "Skipping registry login (SKIP_IMAGE_PUSH=true or no registry configured)"
      fi

# SonarQube scanner
.sonar-scan:
  image: sonarsource/sonar-scanner-cli:latest
  stage: scan
  cache:
    key: "${CI_JOB_NAME}"
    paths:
      - .sonar/cache
  script:
    - |
      sonar-scanner \
        -Dsonar.projectKey=${SONAR_PROJECT_KEY:-$CI_PROJECT_NAME} \
        -Dsonar.host.url=${SONAR_HOST_URL} \
        -Dsonar.token=${SONAR_TOKEN} \
        -Dsonar.sources=${SONAR_SOURCES:-.} \
        -Dsonar.projectName=${CI_PROJECT_NAME} \
        -Dsonar.projectVersion=${CI_COMMIT_SHORT_SHA} \
        -Dsonar.qualitygate.wait=true
  allow_failure: false

# Container image scanning
.container-scan:
  stage: security-scan
  image: aquasec/trivy:latest
  services:
    - docker:24.0.5-dind
  before_script:
    - |
      # Wait for docker to be ready
      for i in $(seq 1 30); do
        if docker info >/dev/null 2>&1; then
          echo "Docker is ready"
          break
        fi
        echo "Waiting for docker... ($i/30)"
        sleep 1
      done
  script:
    - |
      echo "Scanning image ${IMAGE_TAG}"
      if [ -n "${IMAGE_TAG}" ] && docker image inspect ${IMAGE_TAG} >/dev/null 2>&1; then
        trivy image --severity HIGH,CRITICAL --exit-code 0 ${IMAGE_TAG} || echo "Scan completed with findings"
      else
        echo "Image ${IMAGE_TAG} not found locally, skipping scan"
      fi
  allow_failure: true

# Image cleanup
.cleanup-image:
  stage: cleanup
  extends: .docker-base
  script:
    - |
      echo "Starting cleanup for ${IMAGE_TAG}"
      if [ -n "${IMAGE_TAG}" ]; then
        docker rmi ${IMAGE_TAG} 2>/dev/null || echo "Image ${IMAGE_TAG} already removed or not found"
      else
        echo "No image tag specified, skipping cleanup"
      fi
      echo "Cleanup completed successfully"
  when: always
  allow_failure: true
""",

    "templates/java-complete.yml": """
include:
  - local: '/templates/base.yml'

# Build stage
build:
  stage: build
  image: maven:3.8-openjdk-$JAVA_VERSION
  extends: .base-rules
  cache:
    paths:
      - .m2/repository
  script:
    - mvn clean compile
  artifacts:
    paths:
      - target/

# Test stage
test:
  stage: test
  image: maven:3.8-openjdk-$JAVA_VERSION
  extends: .base-rules
  needs: ["build"]
  script:
    - mvn test
  artifacts:
    reports:
      junit:
        - target/surefire-reports/TEST-*.xml
    paths:
      - target/

# SonarQube analysis (runs in parallel with tests)
sonarqube-check:
  extends: .sonar-scan
  needs: ["build"]
  variables:
    SONAR_SOURCES: ${SONAR_SOURCES:-src/main/java}
    SONAR_JAVA_BINARIES: ${SONAR_JAVA_BINARIES:-target/classes}
    SONAR_JUNIT_REPORT_PATHS: target/surefire-reports

# Package application
package:
  stage: package
  image: maven:3.8-openjdk-$JAVA_VERSION
  extends: .base-rules
  needs: ["test"]
  script:
    - mvn package -DskipTests
  artifacts:
    paths:
      - target/*.jar

# Build Docker image
build-image:
  stage: package
  extends: 
    - .docker-base
    - .base-rules
  needs: ["package"]
  script:
    - |
      echo "Building Docker image ${IMAGE_TAG}"
      docker build -t ${IMAGE_TAG} .
      if [ "$SKIP_IMAGE_PUSH" != "true" ]; then
        echo "Pushing image to registry"
        docker push ${IMAGE_TAG} || echo "Push failed, continuing anyway"
      else
        echo "Skipping image push (SKIP_IMAGE_PUSH=true)"
      fi

# Scan Docker image
scan-image:
  extends: .container-scan
  needs: ["build-image"]

# Deploy (dry-run)
deploy:
  stage: deploy
  image: bitnami/kubectl:latest
  extends: .base-rules
  needs: ["scan-image"]
  script:
    - echo "Deploying ${SERVICE_NAME} version ${CI_COMMIT_SHORT_SHA}"
    - kubectl version --client
    - echo "kubectl apply -f k8s/ --dry-run=client"
  environment:
    name: production
    url: https://${SERVICE_NAME}.example.com

# Cleanup
cleanup:
  extends: .cleanup-image
  needs: ["deploy"]
  allow_failure: true
""",

    "templates/python-complete.yml": """
include:
  - local: '/templates/base.yml'

# Build dependencies
build:
  stage: build
  image: python:$PYTHON_VERSION
  extends: .base-rules
  cache:
    paths:
      - .cache/pip
      - venv/
  script:
    - python -m venv venv
    - source venv/bin/activate
    - pip install --upgrade pip
    - pip install -r requirements.txt
  artifacts:
    paths:
      - venv/

# Run tests
test:
  stage: test
  image: python:$PYTHON_VERSION
  extends: .base-rules
  needs: ["build"]
  script:
    - source venv/bin/activate
    - pip install pytest pytest-cov
    - pytest --cov=. --cov-report=xml --cov-report=term || true
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
    paths:
      - coverage.xml

# SonarQube analysis
sonarqube-check:
  extends: .sonar-scan
  needs: ["build"]
  variables:
    SONAR_SOURCES: ${SONAR_SOURCES:-.}
    SONAR_PYTHON_COVERAGE_REPORTPATHS: coverage.xml
    SONAR_PYTHON_VERSION: $PYTHON_VERSION

# Build Docker image
build-image:
  stage: package
  extends:
    - .docker-base
    - .base-rules
  needs: ["test"]
  script:
    - |
      echo "Building Docker image ${IMAGE_TAG}"
      docker build -t ${IMAGE_TAG} .
      if [ "$SKIP_IMAGE_PUSH" != "true" ]; then
        echo "Pushing image to registry"
        docker push ${IMAGE_TAG} || echo "Push failed, continuing anyway"
      else
        echo "Skipping image push (SKIP_IMAGE_PUSH=true)"
      fi

# Security scanning
security-scan:
  stage: security-scan
  image: python:$PYTHON_VERSION
  extends: .base-rules
  needs: ["build"]
  script:
    - source venv/bin/activate
    - pip install safety bandit
    - safety check || true
    - bandit -r . -f json -o bandit-report.json || true
  artifacts:
    reports:
      sast: bandit-report.json

# Image scanning
scan-image:
  extends: .container-scan
  needs: ["build-image"]

# Deploy
deploy:
  stage: deploy
  image: bitnami/kubectl:latest
  extends: .base-rules
  needs: ["scan-image"]
  script:
    - echo "Deploying ${SERVICE_NAME} version ${CI_COMMIT_SHORT_SHA}"
    - echo "kubectl apply -f k8s/ --dry-run=client"

# Cleanup
cleanup:
  extends: .cleanup-image
  needs: ["deploy"]
  allow_failure: true
""",

    "templates/nodejs-complete.yml": """
include:
  - local: '/templates/base.yml'

# Install dependencies
build:
  stage: build
  image: node:$NODE_VERSION
  extends: .base-rules
  cache:
    paths:
      - node_modules/
      - .npm/
  script:
    - npm ci || npm install
  artifacts:
    paths:
      - node_modules/

# Run tests
test:
  stage: test
  image: node:$NODE_VERSION
  extends: .base-rules
  needs: ["build"]
  script:
    - npm test -- --coverage --forceExit || true
  coverage: '/Lines\\s+:\\s+(\\d+\\.?\\d*)%/'
  artifacts:
    reports:
      junit: junit.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage/cobertura-coverage.xml
    paths:
      - coverage/

# Lint code
lint:
  stage: test
  image: node:$NODE_VERSION
  extends: .base-rules
  needs: ["build"]
  script:
    - npm run lint || true

# SonarQube analysis
sonarqube-check:
  extends: .sonar-scan
  needs: ["build"]
  variables:
    SONAR_SOURCES: ${SONAR_SOURCES:-src}
    SONAR_JAVASCRIPT_LCOV_REPORTPATHS: coverage/lcov.info

# Build application
package:
  stage: package
  image: node:$NODE_VERSION
  extends: .base-rules
  needs: ["test"]
  script:
    - npm run build || echo "No build script"
  artifacts:
    paths:
      - dist/
      - build/

# Build Docker image
build-image:
  stage: package
  extends:
    - .docker-base
    - .base-rules
  needs: ["package"]
  script:
    - |
      echo "Building Docker image ${IMAGE_TAG}"
      docker build -t ${IMAGE_TAG} .
      if [ "$SKIP_IMAGE_PUSH" != "true" ]; then
        echo "Pushing image to registry"
        docker push ${IMAGE_TAG} || echo "Push failed, continuing anyway"
      else
        echo "Skipping image push (SKIP_IMAGE_PUSH=true)"
      fi

# Security audit
security-scan:
  stage: security-scan
  image: node:$NODE_VERSION
  extends: .base-rules
  needs: ["build"]
  script:
    - npm audit --audit-level=moderate || true

# Image scan
scan-image:
  extends: .container-scan
  needs: ["build-image"]

# Deploy
deploy:
  stage: deploy
  extends: .base-rules
  needs: ["scan-image"]
  script:
    - echo "Deploying ${SERVICE_NAME} version ${CI_COMMIT_SHORT_SHA}"

# Cleanup
cleanup:
  extends: .cleanup-image
  needs: ["deploy"]
""",

    "templates/react-complete.yml": """
include:
  - local: '/templates/nodejs-complete.yml'

# Override for React specific build
package:
  stage: package
  image: node:$NODE_VERSION
  extends: .base-rules
  needs: ["test"]
  script:
    - npm run build
    - echo "Build size:"
    - du -sh build | cut -f1
  artifacts:
    paths:
      - build/

# Deploy simulation for frontend
deploy:
  stage: deploy
  image: alpine:latest
  extends: .base-rules
  needs: ["scan-image"]
  script:
    - echo "=== Simulating deployment of ${SERVICE_NAME} ==="
    - echo "Target CDN bucket s3://frontend-${SERVICE_NAME}"
    - echo "CloudFront distribution d1234567890.cloudfront.net"
    - echo "Invalidating cache paths /*"
    - echo "Deployment simulation completed successfully"
  environment:
    name: production
    url: https://${SERVICE_NAME}.example.com
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
            'description': 'CI/CD demonstration environment with comprehensive failure scenarios'
        })
        
        # Set namespace-level CI/CD variables
        info("Setting namespace-level CI/CD variables...")
        for var in NAMESPACE_VARIABLES:
            try:
                # Update sonar token if provided
                if var['key'] == 'SONAR_TOKEN' and hasattr(self, 'sonar_token'):
                    var['value'] = self.sonar_token
                    
                group.variables.create(var)
                info(f"  Added namespace variable: {var['key']}")
            except Exception as e:
                warning(f"  Failed to add namespace variable {var['key']}: {e}")
        
        # Create shared pipelines project
        info("Creating shared pipelines repository...")
        shared_project = self.gl.projects.create({
            'name': 'shared-pipelines',
            'namespace_id': group.id,
            'description': 'Shared CI/CD pipeline templates with all lifecycle stages'
        })
        
        # Commit shared templates
        self._commit_files(shared_project, SHARED_TEMPLATES, "feat: comprehensive CI/CD templates for all languages")
        
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
            
            # Always set SONAR_PROJECT_KEY
            project.variables.create({
                'key': 'SONAR_PROJECT_KEY',
                'value': project_name
            })
            
            # Set project-specific variables
            if project_name in PROJECT_VARIABLES:
                for var in PROJECT_VARIABLES[project_name]:
                    try:
                        project.variables.create(var)
                        info(f"    Added variable: {var['key']} = {var['value']}")
                    except Exception as e:
                        warning(f"    Failed to add variable {var['key']}: {e}")
            
            # Create webhooks
            webhooks = [
                {
                    'url': f"{AGENT_WEBHOOK_URL}/gitlab",
                    'pipeline_events': True,
                    'push_events': True,
                    'merge_requests_events': True
                }
            ]
            
            for webhook in webhooks:
                try:
                    project.hooks.create(webhook)
                    info(f"  Added webhook: {webhook['url']}")
                except:
                    pass
            
            # Commit project files
            failure_types = ', '.join(config['failure_types'])
            self._commit_files(
                project, 
                config['files'], 
                f"feat: {config['language']} service with {failure_types} scenarios"
            )
            
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
        """Create comprehensive quality gate"""
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
            
        # Comprehensive conditions for different aspects
        conditions = [
            # Coverage
            {'metric': 'new_coverage', 'op': 'LT', 'error': '80'},
            {'metric': 'new_line_coverage', 'op': 'LT', 'error': '80'},
            {'metric': 'new_branch_coverage', 'op': 'LT', 'error': '70'},
            
            # Reliability (Bugs)
            {'metric': 'new_reliability_rating', 'op': 'GT', 'error': '1'},
            {'metric': 'new_bugs', 'op': 'GT', 'error': '0'},
            
            # Security (Vulnerabilities)
            {'metric': 'new_security_rating', 'op': 'GT', 'error': '1'},
            {'metric': 'new_vulnerabilities', 'op': 'GT', 'error': '0'},
            {'metric': 'new_security_hotspots_reviewed', 'op': 'LT', 'error': '100'},
            
            # Maintainability (Code Smells)
            {'metric': 'new_maintainability_rating', 'op': 'GT', 'error': '1'},
            {'metric': 'new_code_smells', 'op': 'GT', 'error': '5'},
            {'metric': 'new_technical_debt_ratio', 'op': 'GT', 'error': '5'},
            
            # Duplications
            {'metric': 'new_duplicated_lines_density', 'op': 'GT', 'error': '3'},
            {'metric': 'new_duplicated_blocks', 'op': 'GT', 'error': '1'},
            
            # Complexity
            {'metric': 'complexity', 'op': 'GT', 'error': '20'},
            {'metric': 'cognitive_complexity', 'op': 'GT', 'error': '15'},
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
        
        success("Comprehensive quality gate created")
        
    def create_projects(self):
        """Create SonarQube projects"""
        for project_name, config in PROJECTS.items():
            info(f"Creating SonarQube project '{project_name}' ({config['language']})...")
            
            # Create project
            response = self.session.post(
                f"{self.url}/api/projects/create",
                params={
                    'name': project_name,
                    'project': project_name
                }
            )
            
            if response.status_code != 400:  # 400 = already exists
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
            
            # Set project-specific settings based on language
            language_settings = {
                'java': {'sonar.java.source': '11'},
                'python': {'sonar.python.version': '3.9'},
                'nodejs': {'sonar.javascript.node.maxspace': '4096'},
                'javascript': {'sonar.javascript.environments': 'browser'}
            }
            
            if config['language'] in language_settings:
                for key, value in language_settings[config['language']].items():
                    self.session.post(
                        f"{self.url}/api/settings/set",
                        params={
                            'component': project_name,
                            'key': key,
                            'value': value
                        }
                    )
            
        success("SonarQube projects created with language-specific settings")

def print_summary():
    """Print summary of created projects and their failure scenarios"""
    print("\n" + "="*80)
    success("Environment setup complete! Created projects with various failure scenarios:")
    
    print("\n📦 JAVA PROJECTS:")
    print("  • payment-gateway: Spring Boot payment service")
    print("    - Build failure: Missing H2 dependency (intentional)")
    print("    - Quality issues: SQL injection, weak encryption, hardcoded secrets")
    print("    - Code smells: Duplicate code, magic numbers")
    
    print("\n  • auth-service: Spring Boot authentication service")
    print("    - Security vulnerabilities: Plain text passwords, SQL injection")
    print("    - Quality issues: Mass assignment, timing attacks")
    print("    - Dependencies: Vulnerable Log4j version")
    
    print("\n🐍 PYTHON PROJECTS:")
    print("  • user-service: FastAPI user management")
    print("    - Test failures: SQL injection tests, authentication tests")
    print("    - Security: MD5 hashing, hardcoded admin credentials")
    print("    - Quality: Duplicate code, N+1 queries")
    
    print("\n  • notification-api: Django notification service")
    print("    - Quality issues: Template injection, path traversal")
    print("    - Performance: No pagination, blocking I/O")
    print("    - Security: CSRF disabled, debug mode enabled")
    
    print("\n📗 NODE.JS PROJECTS:")
    print("  • inventory-api: Express.js inventory management")
    print("    - Quality gate failures: NoSQL injection, memory leaks")
    print("    - Security: JWT weak secret, hardcoded credentials")
    print("    - Code smells: Duplicate code, no validation")
    
    print("\n⚛️ REACT PROJECTS:")
    print("  • dashboard-ui: React dashboard application")
    print("    - Build issues: Missing optimizations")
    print("    - Security: XSS vulnerabilities, exposed API keys")
    print("    - Quality: Memory leaks, duplicate components")
    
    print("\n🔑 CI/CD VARIABLES:")
    print("  Namespace-level variables set at group level")
    print("  Project-specific variables set for each service")
    
    print("\n🚀 CI/CD PIPELINE STAGES:")
    print("  1. Build - Compile/install dependencies")
    print("  2. Test - Run unit tests with coverage")
    print("  3. Scan - SonarQube analysis (parallel with tests)")
    print("  4. Package - Create artifacts/build images")
    print("  5. Security Scan - Container vulnerability scanning")
    print("  6. Deploy - Simulated deployment (dry-run)")
    print("  7. Cleanup - Remove temporary images")
    
    print("\n🔍 SONARQUBE QUALITY GATE:")
    print("  • Coverage: 80% minimum")
    print("  • Bugs: 0 allowed")
    print("  • Vulnerabilities: 0 allowed")
    print("  • Code Smells: Maximum 5")
    print("  • Security Hotspots: 100% reviewed")
    print("  • Duplications: < 3%")
    print("\n" + "="*80)

if __name__ == "__main__":
    print("=== Enhanced CI/CD Failure Analysis Environment Setup ===\n")
    
    # Get credentials
    gitlab_url = input("GitLab URL [http://localhost:8080]: ").strip() or "http://localhost:8080"
    gitlab_token = getpass.getpass("GitLab Token (api scope): ")
    sonar_url = input("SonarQube URL [http://localhost:9001]: ").strip() or "http://localhost:9001"
    sonar_token = getpass.getpass("SonarQube Token: ")
    
    print("\nThis script will:")
    print(f"- Create GitLab group '{GROUP_NAME}' with shared pipeline templates")
    print(f"- Create {len(PROJECTS)} projects: 2 Java, 2 Python, 1 Node.js, 1 React")
    print(f"- Configure comprehensive CI/CD pipelines with all stages")
    print(f"- Set up namespace and project-level CI/CD variables")
    print(f"- Create strict SonarQube quality gate '{QUALITY_GATE_NAME}'")
    print("- Set up webhooks for automated failure analysis")
    print("\nAll projects will have realistic codebases with various failure scenarios.")
    
    if input("\nProceed? (yes/no): ").lower() != 'yes':
        print("Cancelled")
        sys.exit(0)
        
    try:
        # Initialize managers
        gitlab_manager = GitLabSetup(gitlab_url, gitlab_token)
        gitlab_manager.sonar_token = sonar_token  # Pass sonar token
        sonar_manager = SonarQubeSetup(sonar_url, sonar_token)
        
        # Cleanup
        gitlab_manager.cleanup()
        sonar_manager.cleanup()
        
        # Create environment
        sonar_manager.create_quality_gate()
        sonar_manager.create_projects()
        group = gitlab_manager.create_environment()
        
        # Print summary
        print_summary()
        
        print(f"\n🌐 Access your projects at: {group.web_url}")
        print(f"📊 View quality gates at: {sonar_url}/projects")
        
    except Exception as e:
        error(f"Setup failed: {e}")