# CI/CD Failure Analysis Assistant

An intelligent agent that automatically analyzes GitLab CI/CD pipeline failures, provides actionable fixes, and maintains conversational context for debugging sessions.

## Features

- 🔍 **Automatic Pipeline Analysis**: Detects and analyzes failures via GitLab webhooks
- 🤖 **AI-Powered Solutions**: Uses Claude (via Bedrock or Anthropic) for intelligent fixes
- 💬 **Conversational Debugging**: 4-hour session persistence for iterative problem-solving
- 📊 **Code Quality Integration**: Connects with SonarQube for quality insights
- 🎯 **Historical Learning**: Vector database stores and retrieves similar past issues
- 🖥️ **Teams-Style UI**: Multi-pipeline management with interactive cards

## Architecture

- **Agent Framework**: Strands SDK with custom tools
- **LLM**: Claude 3.5 Sonnet (Bedrock/Anthropic)
- **Database**: PostgreSQL (sessions) + Qdrant (vectors)
- **UI**: Streamlit with adaptive response cards
- **Integrations**: GitLab API + SonarQube API

## Quick Start

1. **Clone the repository**
```bash
git clone <repository>
cd cicd-failure-assistant
```

2. **Configure environment**
```bash
cp .env.example .env
# Edit .env with your credentials
```

3. **Run setup script**
```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
```

4. **Access the services**
- UI: http://localhost:8501
- API: http://localhost:8000
- Qdrant: http://localhost:6333

## Configuration

### Required Environment Variables

```bash
# LLM Provider
LLM_PROVIDER=bedrock  # or anthropic
MODEL_ID=us.anthropic.claude-3-5-sonnet-20241022-v2:0

# AWS (for Bedrock)
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_REGION=us-west-2

# GitLab
GITLAB_URL=http://gitlab:80
GITLAB_TOKEN=your_token

# SonarQube
SONAR_HOST_URL=http://sonarqube:9000
SONAR_TOKEN=your_token
```

### GitLab Webhook Setup

1. Go to GitLab Project → Settings → Webhooks
2. URL: `http://your-host:8000/webhook/gitlab`
3. Trigger: Pipeline events
4. Add webhook

## Testing

Test the webhook integration:
```bash
python scripts/test_webhook.py
```

## Docker Services

- `postgres`: Session database
- `qdrant`: Vector database
- `strands-agent`: Main agent service
- `streamlit-ui`: Web interface

## Development

The project uses Python 3.13 compatible code without version constraints in requirements.txt for maximum flexibility.

### Project Structure
```
├── strands-agent/     # Agent service
│   ├── agent/        # Core agent logic
│   ├── tools/        # Custom tools
│   ├── api/          # REST endpoints
│   └── db/           # Database models
├── ui/               # Streamlit interface
└── scripts/          # Utility scripts
```

## License

Apache 2.0

Below is the whole project Structure

```
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
│   │   ├── strands_agent.py
│   │   ├── prompts.py
│   │   └── llm_provider.py
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
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── gitlab_tools.py
│   │   ├── sonarqube_tools.py
│   │   ├── analysis_tools.py
│   │   ├── context_tools.py
│   │   └── session_tools.py
│   └── utils/
│       ├── __init__.py
│       └── log_processor.py
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
    ├── setup.sh
    └── test_webhook.py
```

```bash
docker exec -it gitlab-runner gitlab-runner register \
  --non-interactive \
  --url "http://gitlab:80" \
  --registration-token "" \
  --description "colima-docker-runner" \
  --tag-list "docker,python,java,javascript" \
  --run-untagged="true" \
  --locked="false" \
  --executor "docker" \
  --description "Host IP Runner" \
  --docker-image "alpine:latest" \
  --docker-privileged=true \
  --docker-network-mode "envathon_porject_3_devops-network"

```