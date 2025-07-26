cicd-failure-assistant/
├── docker-compose.yml
├── .env.example
├── init.sql
├── strands-agent/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── core.py
│   │   ├── tools.py
│   │   └── prompts.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── webhook.py
│   │   └── routes.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   └── session_manager.py
│   ├── vector/
│   │   ├── __init__.py
│   │   └── qdrant_client.py
│   └── mcp/
│       ├── __init__.py
│       └── integrated_runner.py
├── ui/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app.py
│   ├── components/
│   │   ├── __init__.py
│   │   ├── cards.py
│   │   └── pipeline_tabs.py
│   └── utils/
│       ├── __init__.py
│       └── api_client.py
└── scripts/
    └── setup_qdrant_collections.py


