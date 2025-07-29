#!/usr/bin/env python3
"""
Enhanced CI/CD Environment Setup Script
Creates GitLab projects across multiple languages with comprehensive failure scenarios
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
    
    // Another duplicate method with similar logic
    @GetMapping("/details/{id}")
    public Map<String, Object> getPaymentDetails(@PathVariable String id) {
        Map<String, Object> result = new HashMap<>();
        
        // Same hardcoded values - duplication
        Connection conn = null;
        try {
            conn = DriverManager.getConnection("jdbc:mysql://localhost:3306/payments", "root", "password");
        } catch (SQLException e) {
            // Swallowing exception again
        }
        
        result.put("status", "SUCCESS");
        result.put("id", id);
        result.put("details", "Payment details here");
        return result;
    }
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
        
        // Performance issue: N+1 queries
        List<Payment> userPayments = repository.findByUserId(request.getUserId());
        for (Payment p : userPayments) {
            // Individual query for each payment
            repository.findRelatedTransactions(p.getId());
        }
        
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
    
    // Code smell: Long method
    public void reconcilePayments() {
        // 100+ lines of complex logic here...
        List<Payment> payments = repository.findAll();
        Map<String, List<Payment>> groupedPayments = new HashMap<>();
        
        // Complex nested loops - high cyclomatic complexity
        for (Payment payment : payments) {
            if (payment.getStatus().equals("PENDING")) {
                if (payment.getAmount() > 100) {
                    if (payment.getCurrency().equals("USD")) {
                        // More nested conditions...
                        List<Payment> group = groupedPayments.get(payment.getMerchantId());
                        if (group == null) {
                            group = new ArrayList<>();
                            groupedPayments.put(payment.getMerchantId(), group);
                        }
                        group.add(payment);
                    }
                }
            }
        }
        // More complex logic...
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
    
    // Missing validation annotations
    // No getters/setters shown for brevity
    
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

variables:
  SERVICE_NAME: payment-gateway
  SONAR_SOURCES: src/main/java
"""
        }
    },

    # 2. Python FastAPI - Test failure scenario
    "user-management": {
        "description": "Python FastAPI user service - Test failure & security issues",
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

# Vulnerability: Insecure deserialization
@app.post("/import/users")
async def import_users(data: str):
    # Dangerous: Using pickle on user input
    users = pickle.loads(data.encode())
    # Process users...
    return {"imported": len(users)}

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

# Code smell: God object
class UserService:
    def __init__(self):
        self.db = None
        self.cache = {}
        self.validators = []
        self.processors = []
        self.notifiers = []
        # Too many responsibilities
    
    def create_user(self, data): pass
    def update_user(self, data): pass
    def delete_user(self, user_id): pass
    def validate_user(self, data): pass
    def process_user(self, data): pass
    def notify_user(self, user_id): pass
    def cache_user(self, user): pass
    def export_users(self): pass
    def import_users(self): pass
    # ... many more methods
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

def test_import_users():
    # Unsafe test - using pickle
    import pickle
    users = [{"name": "test"}]
    data = pickle.dumps(users).decode('latin-1')
    
    response = client.post("/import/users", json={"data": data})
    assert response.status_code == 200  # Will fail due to encoding issues

def test_admin_access():
    # Missing authentication
    response = client.get("/admin/users")
    assert response.status_code == 401  # Will fail - no auth check

# Flaky test
def test_concurrent_login():
    # This test has race conditions
    import threading
    results = []
    
    def login():
        response = client.post("/login", json={
            "username": "admin",
            "password": "admin123"
        })
        results.append(response.json())
    
    threads = [threading.Thread(target=login) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # Will fail due to race condition in session storage
    assert len(set(r['token'] for r in results)) == 10
""",
            "requirements.txt": """fastapi==0.104.1
uvicorn==0.24.0
sqlalchemy==1.4.32
pytest==7.4.3
httpx==0.25.1
pyjwt==2.8.0
psycopg2-binary==2.9.9
# Vulnerable dependencies
pyyaml==5.3.1  # CVE-2020-1747
requests==2.20.0  # Multiple CVEs
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

variables:
  SERVICE_NAME: user-management
  PYTHON_VERSION: "3.9"
"""
        }
    },

    # 3. Node.js Express - Quality gate failure
    "inventory-tracker": {
        "description": "Node.js inventory service - Quality issues & vulnerabilities",
        "language": "nodejs",
        "failure_types": ["quality", "security"],
        "files": {
            "src/app.js": """
const express = require('express');
const mongoose = require('mongoose');
const bodyParser = require('body-parser');
const jwt = require('jsonwebtoken');
const bcrypt = require('bcrypt');
const fs = require('fs');
const path = require('path');

const app = express();
app.use(bodyParser.json());

// Security issue: Hardcoded connection string
mongoose.connect('mongodb://admin:password@localhost:27017/inventory');

// Vulnerability: No input validation
app.post('/api/inventory/search', (req, res) => {
    const { query } = req.body;
    
    // NoSQL injection vulnerability
    Inventory.find({ $where: \`this.name == '\${query}'\` }, (err, items) => {
        if (err) {
            console.error(err);  // Information disclosure
            return res.status(500).json({ error: err.message });
        }
        res.json(items);
    });
});

// Code smell: Callback hell
app.get('/api/inventory/report', (req, res) => {
    Inventory.find({}, (err, items) => {
        if (err) return res.status(500).send(err);
        
        items.forEach(item => {
            Category.findById(item.categoryId, (err, category) => {
                if (err) return;
                
                Supplier.findById(item.supplierId, (err, supplier) => {
                    if (err) return;
                    
                    Warehouse.findById(item.warehouseId, (err, warehouse) => {
                        if (err) return;
                        
                        // More nested callbacks...
                        // This is callback hell
                    });
                });
            });
        });
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
        console.log(\`Item added: \${name}\`);
        fs.appendFileSync('inventory.log', \`[\${new Date()}] Item added: \${name}\\n\`);
        
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
        console.log(\`Item updated: \${name}\`);
        fs.appendFileSync('inventory.log', \`[\${new Date()}] Item updated: \${name}\\n\`);
        
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

// Performance issue: Synchronous file operations
app.get('/api/inventory/export', (req, res) => {
    const items = Inventory.find({}).lean();  // Missing await
    
    // Blocking I/O
    fs.writeFileSync('export.json', JSON.stringify(items));
    
    res.download('export.json');
});

// Global error handler that leaks information
app.use((err, req, res, next) => {
    console.error(err.stack);  // Full stack trace
    res.status(500).json({
        error: err.message,
        stack: err.stack  // Security issue: exposing stack trace
    });
});

// Server configuration
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(\`Server running on port \${PORT}\`);
});

module.exports = app;
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
            "src/utils/validator.js": """
// Duplicate validation functions (code smell)

function validateEmail(email) {
    // Weak regex
    return /^[^@]+@[^@]+$/.test(email);
}

function validateEmail2(email) {
    // Duplicate function with slightly different logic
    return email.includes('@') && email.includes('.');
}

function validatePhone(phone) {
    // Only works for US numbers
    return /^\\d{10}$/.test(phone);
}

function validatePhone2(phone) {
    // Another duplicate
    return phone.length === 10 && !isNaN(phone);
}

// Unused functions (dead code)
function validateAddress(address) {
    return true;
}

function validateZipCode(zip) {
    return true;
}

module.exports = {
    validateEmail,
    validateEmail2,
    validatePhone,
    validatePhone2,
    validateAddress,
    validateZipCode
};
""",
            "tests/inventory.test.js": """
const request = require('supertest');
const app = require('../src/app');

describe('Inventory API', () => {
    // Tests will pass but don't test security issues
    
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
    
    // Missing security tests
    // Missing edge case tests
    // Missing performance tests
});
""",
            "package.json": """{
  "name": "inventory-tracker",
  "version": "1.0.0",
  "description": "Inventory management service",
  "main": "src/app.js",
  "scripts": {
    "start": "node src/app.js",
    "test": "jest --coverage",
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

variables:
  SERVICE_NAME: inventory-tracker
  NODE_VERSION: "16"
"""
        }
    },

    # 4. Go service - Image scan failure
    "notification-service": {
        "description": "Go notification service - Container security issues",
        "language": "go",
        "failure_types": ["security", "image-scan"],
        "files": {
            "main.go": """package main

import (
    "database/sql"
    "encoding/json"
    "fmt"
    "log"
    "net/http"
    "os"
    "os/exec"
    "crypto/md5"
    _ "github.com/lib/pq"
)

// Hardcoded credentials (security issue)
const (
    dbHost     = "localhost"
    dbPort     = 5432
    dbUser     = "postgres"
    dbPassword = "password123"
    dbName     = "notifications"
)

type Notification struct {
    ID      int    \`json:"id"\`
    UserID  string \`json:"user_id"\`
    Message string \`json:"message"\`
    Type    string \`json:"type"\`
}

var db *sql.DB

func main() {
    initDB()
    
    http.HandleFunc("/notify", handleNotify)
    http.HandleFunc("/template", handleTemplate)
    http.HandleFunc("/broadcast", handleBroadcast)
    http.HandleFunc("/execute", handleExecute)
    
    log.Println("Server starting on :8080")
    log.Fatal(http.ListenAndServe(":8080", nil))
}

func initDB() {
    psqlInfo := fmt.Sprintf("host=%s port=%d user=%s password=%s dbname=%s sslmode=disable",
        dbHost, dbPort, dbUser, dbPassword, dbName)
    
    var err error
    db, err = sql.Open("postgres", psqlInfo)
    if err != nil {
        panic(err)
    }
}

// SQL Injection vulnerability
func handleNotify(w http.ResponseWriter, r *http.Request) {
    userID := r.URL.Query().Get("user_id")
    message := r.URL.Query().Get("message")
    
    // Vulnerable to SQL injection
    query := fmt.Sprintf("INSERT INTO notifications (user_id, message) VALUES ('%s', '%s')", userID, message)
    
    _, err := db.Exec(query)
    if err != nil {
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
    
    w.WriteHeader(http.StatusOK)
    json.NewEncoder(w).Encode(map[string]string{"status": "sent"})
}

// Template injection vulnerability
func handleTemplate(w http.ResponseWriter, r *http.Request) {
    template := r.URL.Query().Get("template")
    data := r.URL.Query().Get("data")
    
    // Dangerous: executing template from user input
    cmd := exec.Command("sh", "-c", fmt.Sprintf("echo '%s' | sed 's/{{data}}/%s/g'", template, data))
    output, err := cmd.Output()
    
    if err != nil {
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
    
    w.Write(output)
}

// Mass assignment vulnerability
func handleBroadcast(w http.ResponseWriter, r *http.Request) {
    var notification Notification
    
    // Decoding all fields including ID (mass assignment)
    err := json.NewDecoder(r.Body).Decode(&notification)
    if err != nil {
        http.Error(w, err.Error(), http.StatusBadRequest)
        return
    }
    
    // No validation or authorization
    query := "SELECT user_id FROM users WHERE active = true"
    rows, _ := db.Query(query)
    defer rows.Close()
    
    for rows.Next() {
        var userID string
        rows.Scan(&userID)
        
        // Weak hashing for notification ID
        hash := md5.Sum([]byte(userID + notification.Message))
        notifID := fmt.Sprintf("%x", hash)
        
        // Send notification (implementation hidden)
        sendNotification(userID, notification.Message, notifID)
    }
    
    json.NewEncoder(w).Encode(map[string]string{"status": "broadcast sent"})
}

// Command injection vulnerability
func handleExecute(w http.ResponseWriter, r *http.Request) {
    command := r.URL.Query().Get("cmd")
    
    // Extremely dangerous: executing arbitrary commands
    cmd := exec.Command("sh", "-c", command)
    output, err := cmd.CombinedOutput()
    
    if err != nil {
        http.Error(w, string(output), http.StatusInternalServerError)
        return
    }
    
    w.Write(output)
}

func sendNotification(userID, message, notifID string) {
    // Dummy implementation
    log.Printf("Sending notification %s to user %s: %s", notifID, userID, message)
}

// Memory leak: goroutines not properly managed
func startWorkers() {
    for i := 0; i < 1000; i++ {
        go func() {
            for {
                // Infinite loop without break condition
                processQueue()
            }
        }()
    }
}

func processQueue() {
    // Simulate work
    // No proper cleanup or channel closing
}
""",
            "go.mod": """module notification-service

go 1.19

require (
    github.com/lib/pq v1.10.2
    github.com/gorilla/mux v1.7.4
)

// Using outdated versions with known vulnerabilities
require (
    github.com/dgrijalva/jwt-go v3.2.0+incompatible
    gopkg.in/yaml.v2 v2.2.8
)
""",
            "notification_test.go": """package main

import (
    "testing"
    "net/http"
    "net/http/httptest"
)

func TestHandleNotify(t *testing.T) {
    req, _ := http.NewRequest("GET", "/notify?user_id=1&message=test", nil)
    rr := httptest.NewRecorder()
    handler := http.HandlerFunc(handleNotify)
    
    handler.ServeHTTP(rr, req)
    
    // Weak test - doesn't check SQL injection
    if status := rr.Code; status != http.StatusOK {
        t.Errorf("handler returned wrong status code: got %v want %v",
            status, http.StatusOK)
    }
}

// Missing security tests
// Missing performance tests
// Missing error case tests
""",
            "Dockerfile": """# Using outdated base image with vulnerabilities
FROM golang:1.16-alpine

# Running as root
WORKDIR /app

# Copying everything including secrets
COPY . .

# Building without security flags
RUN go build -o notification-service .

# Installing unnecessary packages (increases attack surface)
RUN apk add --no-cache curl wget netcat-openbsd

# Exposing too many ports
EXPOSE 8080 8081 8082 9090

# No health check
# No user creation (runs as root)

CMD ["./notification-service"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/golang-complete.yml'

variables:
  SERVICE_NAME: notification-service
  GO_VERSION: "1.19"
"""
        }
    },

    # 5. React Frontend - Build optimization issues
    "customer-portal": {
        "description": "React customer portal - Build and quality issues",
        "language": "javascript",
        "failure_types": ["build", "quality"],
        "files": {
            "src/App.js": """import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

// Hardcoded API keys (security issue)
const API_KEY = 'sk_live_abcd1234567890';
const API_URL = 'https://api.example.com';

function App() {
  const [user, setUser] = useState(null);
  const [data, setData] = useState([]);
  
  // Performance issue: API call on every render
  useEffect(() => {
    fetchUserData();
    fetchAllData();
  });  // Missing dependency array
  
  // Security: Storing sensitive data in localStorage
  const fetchUserData = async () => {
    const response = await axios.get(\`\${API_URL}/user\`);
    localStorage.setItem('user_token', response.data.token);
    localStorage.setItem('user_password', response.data.password); // Very bad!
    setUser(response.data);
  };
  
  // Performance: Fetching all data without pagination
  const fetchAllData = async () => {
    const response = await axios.get(\`\${API_URL}/all-data\`);
    setData(response.data); // Could be huge
  };
  
  // XSS vulnerability
  const renderHTML = (html) => {
    return <div dangerouslySetInnerHTML={{ __html: html }} />;
  };
  
  // Memory leak: Event listener not cleaned up
  useEffect(() => {
    window.addEventListener('resize', handleResize);
    // Missing cleanup
  }, []);
  
  const handleResize = () => {
    console.log('Window resized');
  };
  
  return (
    <div className="App">
      <h1>Customer Portal</h1>
      
      {/* Rendering user input without sanitization */}
      {user && renderHTML(user.bio)}
      
      {/* Performance: Rendering large lists without virtualization */}
      <div>
        {data.map((item, index) => (
          <div key={index}> {/* Using index as key - bad practice */}
            <h3>{item.title}</h3>
            <p>{item.description}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// Duplicate component (code smell)
function UserCard({ user }) {
  return (
    <div>
      <h2>{user.name}</h2>
      <p>{user.email}</p>
    </div>
  );
}

// Another duplicate with slight variation
function UserCardWithAvatar({ user }) {
  return (
    <div>
      <img src={user.avatar} alt={user.name} />
      <h2>{user.name}</h2>
      <p>{user.email}</p>
    </div>
  );
}

export default App;
""",
            "src/utils/auth.js": """// Authentication utilities with security issues

export const login = async (username, password) => {
  // Client-side validation only (security issue)
  if (username === 'admin' && password === 'admin') {
    return { token: 'fake-jwt-token' };
  }
  
  // Logging sensitive data
  console.log('Login attempt:', username, password);
  
  // Weak encryption
  const encryptedPassword = btoa(password); // Base64 is not encryption!
  
  const response = await fetch('/api/login', {
    method: 'POST',
    body: JSON.stringify({ username, password: encryptedPassword })
  });
  
  return response.json();
};

// Insecure token storage
export const saveToken = (token) => {
  // Storing in localStorage (vulnerable to XSS)
  localStorage.setItem('auth_token', token);
  
  // Also storing in cookie without secure flags
  document.cookie = \`token=\${token}\`;
};

// No token expiration check
export const isAuthenticated = () => {
  return localStorage.getItem('auth_token') !== null;
};
""",
            "src/components/Payment.jsx": """import React, { useState } from 'react';

const Payment = () => {
  const [cardNumber, setCardNumber] = useState('');
  const [cvv, setCvv] = useState('');
  
  // Security: Credit card data in state (can be exposed in React DevTools)
  const [creditCardData, setCreditCardData] = useState({});
  
  const handleSubmit = async (e) => {
    e.preventDefault();
    
    // Logging sensitive payment data
    console.log('Payment data:', { cardNumber, cvv });
    
    // Sending payment data to analytics (security issue)
    window.gtag('event', 'payment', {
      card_number: cardNumber,
      cvv: cvv
    });
    
    // No HTTPS check
    const response = await fetch('http://api.example.com/payment', {
      method: 'POST',
      body: JSON.stringify({ cardNumber, cvv })
    });
  };
  
  return (
    <form onSubmit={handleSubmit}>
      <input
        type="text"
        value={cardNumber}
        onChange={(e) => setCardNumber(e.target.value)}
        placeholder="Card Number"
        autoComplete="off" // Not preventing autocomplete properly
      />
      <input
        type="text" // Should be type="password"
        value={cvv}
        onChange={(e) => setCvv(e.target.value)}
        placeholder="CVV"
      />
      <button type="submit">Pay Now</button>
    </form>
  );
};

// Code duplication
const PaymentForm = () => {
  // Duplicate logic from above
  const [cardNumber, setCardNumber] = useState('');
  const [cvv, setCvv] = useState('');
  
  // ... same implementation
};

export default Payment;
""",
            "package.json": """{
  "name": "customer-portal",
  "version": "1.0.0",
  "dependencies": {
    "react": "17.0.2",
    "react-dom": "17.0.2",
    "axios": "0.21.1",
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
    "test": "react-scripts test",
    "eject": "react-scripts eject"
  },
  "browserslist": {
    "production": [">0.2%", "not dead", "not op_mini all"],
    "development": ["last 1 chrome version", "last 1 firefox version"]
  }
}
""",
            "Dockerfile": """FROM node:14-alpine

WORKDIR /app

# Inefficient: copying everything before install
COPY . .
RUN npm install
RUN npm run build

# Using nginx with default config (security headers missing)
FROM nginx:alpine
COPY --from=0 /app/build /usr/share/nginx/html

# No custom nginx config
# No security headers
# No rate limiting

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/react-complete.yml'

variables:
  SERVICE_NAME: customer-portal
  NODE_VERSION: "16"
"""
        }
    },

    # 6. .NET Core API - Deployment failure
    "order-processing": {
        "description": ".NET Core order processing API - Deployment issues",
        "language": "dotnet",
        "failure_types": ["deploy", "security"],
        "files": {
            "Controllers/OrderController.cs": """using Microsoft.AspNetCore.Mvc;
using System.Data.SqlClient;
using System.Threading.Tasks;
using OrderProcessing.Models;

namespace OrderProcessing.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class OrderController : ControllerBase
    {
        private readonly string connectionString = "Server=localhost;Database=Orders;User Id=sa;Password=Password123!;";
        
        // SQL Injection vulnerability
        [HttpGet("{orderId}")]
        public async Task<IActionResult> GetOrder(string orderId)
        {
            using var connection = new SqlConnection(connectionString);
            var query = $"SELECT * FROM Orders WHERE OrderId = '{orderId}'";
            
            using var command = new SqlCommand(query, connection);
            await connection.OpenAsync();
            
            var reader = await command.ExecuteReaderAsync();
            if (reader.Read())
            {
                return Ok(new Order
                {
                    OrderId = reader["OrderId"].ToString(),
                    CustomerId = reader["CustomerId"].ToString(),
                    Total = decimal.Parse(reader["Total"].ToString())
                });
            }
            
            return NotFound();
        }
        
        // Mass assignment vulnerability
        [HttpPost]
        public async Task<IActionResult> CreateOrder([FromBody] Order order)
        {
            // No validation
            // User can set any field including OrderId and Status
            
            using var connection = new SqlConnection(connectionString);
            var query = $@"INSERT INTO Orders (OrderId, CustomerId, Total, Status) 
                          VALUES ('{order.OrderId}', '{order.CustomerId}', {order.Total}, '{order.Status}')";
            
            using var command = new SqlCommand(query, connection);
            await connection.OpenAsync();
            await command.ExecuteNonQueryAsync();
            
            return Ok(order);
        }
        
        // Information disclosure
        [HttpGet("error-test")]
        public IActionResult ErrorTest()
        {
            try
            {
                throw new System.Exception("Database connection failed: Server=prod-db;User=admin;Password=SuperSecret123");
            }
            catch (System.Exception ex)
            {
                // Returning full exception details
                return StatusCode(500, new { 
                    error = ex.Message, 
                    stackTrace = ex.StackTrace,
                    innerException = ex.InnerException?.Message 
                });
            }
        }
    }
}
""",
            "Models/Order.cs": """namespace OrderProcessing.Models
{
    public class Order
    {
        public string OrderId { get; set; }
        public string CustomerId { get; set; }
        public decimal Total { get; set; }
        public string Status { get; set; }
        
        // No validation attributes
        // No data annotations
    }
}
""",
            "Startup.cs": """using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.Extensions.DependencyInjection;

namespace OrderProcessing
{
    public class Startup
    {
        public void ConfigureServices(IServiceCollection services)
        {
            services.AddControllers();
            
            // Missing security headers
            // Missing CORS configuration
            // Missing authentication
        }
        
        public void Configure(IApplicationBuilder app, IWebHostEnvironment env)
        {
            // Always using development exception page
            app.UseDeveloperExceptionPage();
            
            app.UseRouting();
            
            // Missing authorization
            // Missing HTTPS redirection
            
            app.UseEndpoints(endpoints =>
            {
                endpoints.MapControllers();
            });
        }
    }
}
""",
            "OrderProcessing.csproj": """<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>net6.0</TargetFramework>
  </PropertyGroup>
  
  <ItemGroup>
    <PackageReference Include="Microsoft.AspNetCore.App" />
    <PackageReference Include="System.Data.SqlClient" Version="4.8.1" />
    <!-- Vulnerable package versions -->
    <PackageReference Include="Newtonsoft.Json" Version="10.0.3" />
  </ItemGroup>
</Project>
""",
            "Dockerfile": """FROM mcr.microsoft.com/dotnet/sdk:6.0 AS build
WORKDIR /src

# Copy everything (including secrets)
COPY . .
RUN dotnet restore
RUN dotnet build -c Release

FROM mcr.microsoft.com/dotnet/aspnet:6.0
WORKDIR /app

# Running as root
COPY --from=build /src/bin/Release/net6.0 .

# Hardcoded environment variables
ENV ASPNETCORE_ENVIRONMENT=Production
ENV ConnectionStrings__DefaultConnection="Server=prod;Database=Orders;User=sa;Password=Password123!"

EXPOSE 80
ENTRYPOINT ["dotnet", "OrderProcessing.dll"]
""",
            ".gitlab-ci.yml": """include:
  - project: 'cicd-demo/shared-pipelines'
    ref: main
    file: '/templates/dotnet-complete.yml'

variables:
  SERVICE_NAME: order-processing
  DOTNET_VERSION: "6.0"
"""
        }
    }
}

# Enhanced shared CI/CD templates
SHARED_TEMPLATES = {
    "templates/base.yml": """
# Base template with all stages
variables:
  DOCKER_DRIVER: overlay2
  DOCKER_TLS_CERTDIR: ""
  SONAR_USER_HOME: "${CI_PROJECT_DIR}/.sonar"
  GIT_DEPTH: "0"
  IMAGE_TAG: "${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA}"

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
    - echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin $CI_REGISTRY

# SonarQube scanner
.sonar-scan:
  image: sonarsource/sonar-scanner-cli:latest
  stage: scan
  parallel:
    matrix:
      - SCAN_TYPE: [code, security]
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
        -Dsonar.sources=. \
        -Dsonar.projectName=${CI_PROJECT_NAME} \
        -Dsonar.projectVersion=${CI_COMMIT_SHORT_SHA} \
        -Dsonar.qualitygate.wait=true
  allow_failure: false

# Container image scanning
.container-scan:
  stage: security-scan
  image: aquasec/trivy:latest
  script:
    - trivy image --severity HIGH,CRITICAL --exit-code 1 ${IMAGE_TAG}
  allow_failure: true

# Image cleanup
.cleanup-image:
  stage: cleanup
  extends: .docker-base
  script:
    - docker rmi ${IMAGE_TAG} || true
  when: always
""",

    "templates/java-complete.yml": """
include:
  - local: '/templates/base.yml'

# Build stage
build:
  stage: build
  image: maven:3.8-openjdk-11
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
  image: maven:3.8-openjdk-11
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
    SONAR_SOURCES: "src/main/java"
    SONAR_JAVA_BINARIES: "target/classes"
    SONAR_JUNIT_REPORT_PATHS: "target/surefire-reports"

# Package application
package:
  stage: package
  image: maven:3.8-openjdk-11
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
    - docker build -t ${IMAGE_TAG} .
    - docker push ${IMAGE_TAG}

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
""",

    "templates/python-complete.yml": """
include:
  - local: '/templates/base.yml'

# Build dependencies
build:
  stage: build
  image: python:${PYTHON_VERSION:-3.9}
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
  image: python:${PYTHON_VERSION:-3.9}
  extends: .base-rules
  needs: ["build"]
  script:
    - source venv/bin/activate
    - pip install pytest pytest-cov
    - pytest --cov=. --cov-report=xml --cov-report=term
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
    SONAR_SOURCES: "."
    SONAR_PYTHON_COVERAGE_REPORTPATHS: "coverage.xml"
    SONAR_PYTHON_VERSION: ${PYTHON_VERSION:-3.9}

# Build Docker image
build-image:
  stage: package
  extends:
    - .docker-base
    - .base-rules
  needs: ["test"]
  script:
    - docker build -t ${IMAGE_TAG} .
    - docker push ${IMAGE_TAG}

# Security scanning
security-scan:
  stage: security-scan
  image: python:${PYTHON_VERSION:-3.9}
  extends: .base-rules
  needs: ["build"]
  script:
    - source venv/bin/activate
    - pip install safety bandit
    - safety check
    - bandit -r . -f json -o bandit-report.json
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
""",

    "templates/nodejs-complete.yml": """
include:
  - local: '/templates/base.yml'

# Install dependencies
build:
  stage: build
  image: node:${NODE_VERSION:-16}
  extends: .base-rules
  cache:
    paths:
      - node_modules/
  script:
    - npm ci || npm install
  artifacts:
    paths:
      - node_modules/

# Run tests
test:
  stage: test
  image: node:${NODE_VERSION:-16}
  extends: .base-rules
  needs: ["build"]
  script:
    - npm test -- --coverage
  coverage: '/Lines\\s+:\\s+(\\d+\\.?\\d*)%/'
  artifacts:
    reports:
      junit: junit.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage/cobertura-coverage.xml

# Lint code
lint:
  stage: test
  image: node:${NODE_VERSION:-16}
  extends: .base-rules
  needs: ["build"]
  script:
    - npm run lint || true

# SonarQube analysis
sonarqube-check:
  extends: .sonar-scan
  needs: ["build"]
  variables:
    SONAR_SOURCES: "src"
    SONAR_JAVASCRIPT_LCOV_REPORTPATHS: "coverage/lcov.info"

# Build application
package:
  stage: package
  image: node:${NODE_VERSION:-16}
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
    - docker build -t ${IMAGE_TAG} .
    - docker push ${IMAGE_TAG}

# Security audit
security-scan:
  stage: security-scan
  image: node:${NODE_VERSION:-16}
  extends: .base-rules
  needs: ["build"]
  script:
    - npm audit --audit-level=moderate

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

    "templates/golang-complete.yml": """
include:
  - local: '/templates/base.yml'

# Build stage
build:
  stage: build
  image: golang:${GO_VERSION:-1.19}
  extends: .base-rules
  script:
    - go mod download
    - go build -o ${SERVICE_NAME} .
  artifacts:
    paths:
      - ${SERVICE_NAME}

# Test stage
test:
  stage: test
  image: golang:${GO_VERSION:-1.19}
  extends: .base-rules
  needs: ["build"]
  script:
    - go test -v -coverprofile=coverage.out ./...
    - go tool cover -func=coverage.out
  coverage: '/total:\s+\(statements\)\s+(\d+\.\d+)%/'
  artifacts:
    paths:
      - coverage.out

# SonarQube analysis
sonarqube-check:
  extends: .sonar-scan
  needs: ["build"]
  variables:
    SONAR_SOURCES: "."
    SONAR_GO_COVERAGE_REPORTPATHS: "coverage.out"

# Static analysis
staticcheck:
  stage: test
  image: golang:${GO_VERSION:-1.19}
  extends: .base-rules
  needs: ["build"]
  script:
    - go install honnef.co/go/tools/cmd/staticcheck@latest
    - staticcheck ./...

# Build Docker image
build-image:
  stage: package
  extends:
    - .docker-base
    - .base-rules
  needs: ["test"]
  script:
    - docker build -t ${IMAGE_TAG} .
    - docker push ${IMAGE_TAG}

# Security scan
security-scan:
  stage: security-scan
  image: golang:${GO_VERSION:-1.19}
  extends: .base-rules
  needs: ["build"]
  script:
    - go install github.com/securego/gosec/v2/cmd/gosec@latest
    - gosec -fmt json -out gosec-report.json ./...
  artifacts:
    reports:
      sast: gosec-report.json

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
  image: node:${NODE_VERSION:-16}
  extends: .base-rules
  needs: ["test"]
  script:
    - npm run build
    - echo "Build size: $(du -sh build | cut -f1)"
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
    - echo "Target: CDN bucket s3://frontend-${SERVICE_NAME}"
    - echo "CloudFront distribution: d1234567890.cloudfront.net"
    - echo "Invalidating cache paths: /*"
    - echo "Deployment simulation completed successfully"
  environment:
    name: production
    url: https://${SERVICE_NAME}.example.com
""",

    "templates/dotnet-complete.yml": """
include:
  - local: '/templates/base.yml'

# Build stage
build:
  stage: build
  image: mcr.microsoft.com/dotnet/sdk:${DOTNET_VERSION:-6.0}
  extends: .base-rules
  script:
    - dotnet restore
    - dotnet build -c Release
  artifacts:
    paths:
      - bin/
      - obj/

# Test stage
test:
  stage: test
  image: mcr.microsoft.com/dotnet/sdk:${DOTNET_VERSION:-6.0}
  extends: .base-rules
  needs: ["build"]
  script:
    - dotnet test --no-build -c Release --logger "trx;LogFileName=test-results.trx"
  artifacts:
    reports:
      junit: test-results.trx
    paths:
      - test-results.trx

# SonarQube analysis
sonarqube-check:
  stage: scan
  image: mcr.microsoft.com/dotnet/sdk:${DOTNET_VERSION:-6.0}
  extends: .base-rules
  needs: ["build"]
  script:
    - apt-get update && apt-get install -y openjdk-11-jre
    - dotnet tool install --global dotnet-sonarscanner
    - export PATH="$PATH:$HOME/.dotnet/tools"
    - |
      dotnet sonarscanner begin \
        /k:"${SONAR_PROJECT_KEY:-$CI_PROJECT_NAME}" \
        /d:sonar.host.url="${SONAR_HOST_URL}" \
        /d:sonar.token="${SONAR_TOKEN}"
    - dotnet build
    - dotnet sonarscanner end /d:sonar.token="${SONAR_TOKEN}"

# Publish application
package:
  stage: package
  image: mcr.microsoft.com/dotnet/sdk:${DOTNET_VERSION:-6.0}
  extends: .base-rules
  needs: ["test"]
  script:
    - dotnet publish -c Release -o ./publish
  artifacts:
    paths:
      - publish/

# Build Docker image
build-image:
  stage: package
  extends:
    - .docker-base
    - .base-rules
  needs: ["package"]
  script:
    - docker build -t ${IMAGE_TAG} .
    - docker push ${IMAGE_TAG}

# Security scan
security-scan:
  stage: security-scan
  image: mcr.microsoft.com/dotnet/sdk:${DOTNET_VERSION:-6.0}
  extends: .base-rules
  needs: ["build"]
  script:
    - dotnet list package --vulnerable --include-transitive

# Image scan
scan-image:
  extends: .container-scan
  needs: ["build-image"]

# Deploy simulation
deploy:
  stage: deploy
  image: alpine:latest
  extends: .base-rules
  needs: ["scan-image"]
  script:
    - echo "=== Simulating deployment of ${SERVICE_NAME} ==="
    - echo "Target namespace: production"
    - echo "Deployment method: Rolling update"
    - echo "Replicas: 3"
    - echo "Health check endpoint: /health"
    - echo "Simulating Kubernetes deployment..."
    - sleep 2
    - echo "Deployment simulation completed successfully"
  environment:
    name: production
    url: https://api-${SERVICE_NAME}.example.com

# Cleanup
cleanup:
  extends: .cleanup-image
  needs: ["deploy"]
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
        
        # Set group variables
        info("Setting group-level CI/CD variables...")
        variables = [
            {'key': 'SONAR_HOST_URL', 'value': 'http://sonarqube:9000'},
            {'key': 'SONAR_TOKEN', 'value': sonar_token, 'masked': True},
            {'key': 'CI_REGISTRY', 'value': 'registry.gitlab.com'},
            {'key': 'CI_REGISTRY_USER', 'value': 'gitlab-ci-token'},
            {'key': 'CI_REGISTRY_PASSWORD', 'value': '${CI_JOB_TOKEN}'},
            {'key': 'DOCKER_HOST', 'value': 'tcp://docker:2375'},
            {'key': 'DOCKER_TLS_CERTDIR', 'value': ''}
        ]
        
        for var in variables:
            try:
                group.variables.create(var)
            except:
                pass  # Variable might already exist
        
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
            
            # Set project variables
            project.variables.create({
                'key': 'SONAR_PROJECT_KEY',
                'value': project_name
            })
            
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
                'go': {'sonar.go.coverage.reportPaths': 'coverage.out'},
                'javascript': {'sonar.javascript.environments': 'browser'},
                'dotnet': {'sonar.cs.vscoveragexml.reportsPaths': 'coverage.xml'}
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
    print("  • payment-gateway: Spring Boot service")
    print("    - Build failure: Missing H2 dependency")
    print("    - Quality issues: SQL injection, weak encryption, hardcoded secrets")
    print("    - Code smells: Duplicate code, magic numbers, long methods")
    
    print("\n🐍 PYTHON PROJECTS:")
    print("  • user-management: FastAPI service")
    print("    - Test failures: SQL injection tests, race conditions")
    print("    - Security: Pickle deserialization, MD5 hashing, hardcoded admin")
    print("    - Quality: God object, N+1 queries, duplicate code")
    
    print("\n📗 NODE.JS PROJECTS:")
    print("  • inventory-tracker: Express.js service")
    print("    - Quality gate failure: Callback hell, memory leaks")
    print("    - Security: NoSQL injection, JWT weak secret")
    print("    - Code smells: Duplicate validation, synchronous I/O")
    
    print("\n🔷 GO PROJECTS:")
    print("  • notification-service: HTTP service")
    print("    - Image scan failures: Outdated base image, running as root")
    print("    - Security: Command injection, SQL injection")
    print("    - Quality: Goroutine leaks, hardcoded credentials")
    
    print("\n⚛️ REACT PROJECTS:")
    print("  • customer-portal: Frontend application")
    print("    - Build issues: Large bundle size, missing optimizations")
    print("    - Security: XSS vulnerabilities, exposed API keys")
    print("    - Quality: Performance issues, memory leaks")
    
    print("\n🔶 .NET PROJECTS:")
    print("  • order-processing: .NET Core API")
    print("    - Deployment failures: Missing configuration")
    print("    - Security: SQL injection, mass assignment")
    print("    - Quality: No validation, information disclosure")
    
    print("\n🚀 CI/CD PIPELINE STAGES:")
    print("  1. Build - Compile/install dependencies")
    print("  2. Test - Run unit tests with coverage")
    print("  3. Scan - SonarQube analysis (parallel with build)")
    print("  4. Package - Create artifacts/build images")
    print("  5. Security Scan - Trivy container scanning")
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
    global gitlab_url, sonar_url, sonar_token
    gitlab_url = input("GitLab URL [http://localhost:8080]: ").strip() or "http://localhost:8080"
    gitlab_token = getpass.getpass("GitLab Token (api scope): ")
    sonar_url = input("SonarQube URL [http://localhost:9001]: ").strip() or "http://localhost:9001"
    sonar_token = getpass.getpass("SonarQube Token: ")
    
    print("\nThis script will:")
    print(f"- Create GitLab group '{GROUP_NAME}' with shared pipeline templates")
    print(f"- Create {len(PROJECTS)} projects across Java, Python, Node.js, Go, React, and .NET")
    print(f"- Configure comprehensive CI/CD pipelines with all stages")
    print(f"- Create strict SonarQube quality gate '{QUALITY_GATE_NAME}'")
    print("- Set up webhooks for automated failure analysis")
    print("\nAll projects will have realistic codebases with various failure scenarios.")
    
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
        group = gitlab_manager.create_environment()
        
        # Print summary
        print_summary()
        
        print(f"\n🌐 Access your projects at: {group.web_url}")
        print(f"📊 View quality gates at: {sonar_url}/projects")
        
    except Exception as e:
        error(f"Setup failed: {e}")