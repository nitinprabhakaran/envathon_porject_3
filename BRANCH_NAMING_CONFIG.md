# Configurable Branch Naming with Session Tracking

This document explains how to configure custom branch naming patterns for the CI/CD Pipeline Failure Analysis System, including unique session-based identifiers for improved traceability.

## Overview

The system creates branches for different types of fixes with unique identifiers:
- **Pipeline fixes**: For CI/CD pipeline failures
- **Quality fixes**: For SonarQube quality gate failures  
- **General fixes**: For other types of issues

Each branch includes a session identifier and timestamp for uniqueness and traceability.

## Branch Naming Pattern

### Format
All branches follow this pattern:
```
<prefix><session_id_short>_<timestamp>_<description>
```

Where:
- **prefix**: Configurable prefix (e.g., `fix/pipeline_`, `cicd-assistant/quality_`)
- **session_id_short**: First 6 characters of the session UUID (no hyphens)
- **timestamp**: Current date in YYYYMMDD format
- **description**: Brief description using underscores

### Examples
```
fix/pipeline_a1b2c3_20250816_build_dependency_fix
fix/sonarqube_d4e5f6_20250816_security_vulnerabilities
cicd-assistant/m4n5o6_20250816_documentation_update
```

## Configuration

### Environment Variables

Set these environment variables to customize branch naming:

```bash
# Pipeline fix branches (default: fix/pipeline_)
BRANCH_PREFIX_PIPELINE=fix/pipeline_

# Quality/SonarQube fix branches (default: fix/sonarqube_)  
BRANCH_PREFIX_QUALITY=fix/sonarqube_

# General purpose fix branches (default: cicd-assistant/)
BRANCH_PREFIX_GENERAL=cicd-assistant/
```

### Configuration Methods

#### 1. Using .env file (Recommended)

Create or update your `.env` file in the project root:

```bash
# Branch naming patterns
BRANCH_PREFIX_PIPELINE=cicd-assistant/pipeline_
BRANCH_PREFIX_QUALITY=cicd-assistant/quality_
BRANCH_PREFIX_GENERAL=cicd-assistant/general_
```

#### 2. Using Docker Compose environment

Set environment variables in your shell before running docker-compose:

```bash
export BRANCH_PREFIX_PIPELINE="automated-fix/pipeline-"
export BRANCH_PREFIX_QUALITY="automated-fix/quality-"
export BRANCH_PREFIX_GENERAL="automated-fix/general-"

docker-compose up
```

#### 3. Using Docker Compose override

Create a `docker-compose.override.yml` file:

```yaml
services:
  strands-agent:
    environment:
      - BRANCH_PREFIX_PIPELINE=my-org/pipeline-fix/
      - BRANCH_PREFIX_QUALITY=my-org/quality-fix/
      - BRANCH_PREFIX_GENERAL=my-org/general-fix/
  
  streamlit-ui:
    environment:
      - BRANCH_PREFIX_PIPELINE=my-org/pipeline-fix/
      - BRANCH_PREFIX_QUALITY=my-org/quality-fix/
      - BRANCH_PREFIX_GENERAL=my-org/general-fix/
```

## Examples

### Example 1: Organization-based prefixes

```bash
BRANCH_PREFIX_PIPELINE=mycompany/ci-fix/
BRANCH_PREFIX_QUALITY=mycompany/quality-fix/
BRANCH_PREFIX_GENERAL=mycompany/automated-fix/
```

This creates branches like:
- `mycompany/ci-fix/a1b2c3_20250816_build_dependency_update`
- `mycompany/quality-fix/d4e5f6_20250816_security_vulnerabilities`

### Example 2: Workflow-based prefixes

```bash
BRANCH_PREFIX_PIPELINE=workflow/pipeline/
BRANCH_PREFIX_QUALITY=workflow/quality/
BRANCH_PREFIX_GENERAL=workflow/general/
```

This creates branches like:
- `workflow/pipeline/g7h8i9_20250816_test_configuration_fix`
- `workflow/quality/j1k2l3_20250816_code_smell_cleanup`

### Example 3: Simple prefixes

```bash
BRANCH_PREFIX_PIPELINE=fix-
BRANCH_PREFIX_QUALITY=quality-
BRANCH_PREFIX_GENERAL=auto-
```

This creates branches like:
- `fix-m4n5o6_20250816_build_error_resolution`
- `quality-p7q8r9_20250816_sonar_issues_batch`

## Impact on System Components

### Enhanced Traceability
- **Session Tracking**: Each branch can be traced back to its originating analysis session
- **Timestamp Ordering**: Branches are chronologically sortable by creation date
- **Unique Identification**: No branch name conflicts even with concurrent sessions
- **Webhook Optimization**: Pipeline success/failure handlers can quickly identify the correct session

### Agent Behavior
- The LLM agent automatically generates session-based branch names
- Session UUID is extracted from context and shortened to 6 characters  
- Current date is automatically included in the timestamp
- Branch naming guidelines are dynamically included in agent prompts

### UI Behavior  
- The Streamlit UI recognizes fix branches based on configured prefixes
- Session information can be extracted from branch names for enhanced display
- Status indicators show session correlation and timing information
- Branch history is more meaningful with session and timestamp data

### Webhook Processing
- **Fast Session Lookup**: Branch names contain session IDs for direct session matching
- **Improved Accuracy**: No more iterating through all sessions to find matches
- **Better Logging**: Webhook handlers can log session-specific information
- **Conflict Resolution**: Multiple concurrent fixes are properly differentiated

## Session Tracking Benefits

### Direct Session Correlation
- **Instant Matching**: Webhook handlers can immediately identify which session created a branch
- **Reduced Database Queries**: No need to check all active sessions for branch matches
- **Concurrent Session Support**: Multiple sessions can work on the same project without conflicts

### Enhanced Debugging
- **Branch Genealogy**: Easy to trace which analysis session led to which fix
- **Timeline Reconstruction**: Session timestamps help understand the fix timeline
- **Performance Monitoring**: Track how long from session creation to successful fix

### Operational Insights
- **Fix Success Rates**: Correlate successful fixes with specific analysis sessions
- **Pattern Recognition**: Identify which types of sessions lead to successful fixes
- **Resource Planning**: Understand session duration and fix complexity patterns

## Migration from Hardcoded Prefixes

If you have existing fix branches with the old hardcoded prefixes (`fix/pipeline_`, `fix/sonarqube_`), they will continue to work. The system supports:

1. **Backward compatibility**: Old branches are still recognized and tracked
2. **Mixed environments**: You can have both old and new branch patterns
3. **Gradual migration**: Change the configuration when convenient

## Validation

After changing branch prefixes:

1. **Test branch creation**: Create a new MR to verify branch naming
2. **Check UI recognition**: Ensure the UI correctly identifies fix branches  
3. **Verify webhook processing**: Confirm pipeline success detection works
4. **Review logs**: Check that branch pattern matching is working

## Best Practices

### Branch Naming Conventions
- **Keep prefixes short** but descriptive
- **Use consistent separators** (/, -, _)
- **Include trailing separators** if you want them (e.g., `fix/` not `fix`)
- **Avoid special characters** that might cause Git issues

### Organizational Standards
- **Align with team conventions**: Match your existing branch naming standards
- **Consider automation tools**: Ensure compatibility with other CI/CD tools
- **Document team decisions**: Share the chosen patterns with your team

### Environment Management
- **Use .env files**: Keep configuration in version-controlled .env files
- **Environment-specific configs**: Different patterns for dev/staging/prod if needed
- **Backup old configs**: Keep a record of previous configurations

## Troubleshooting

### Branch not recognized as fix branch
- Check that the branch name starts with the exact configured prefix
- Verify environment variables are loaded correctly
- Check logs for branch pattern matching messages

### UI not showing correct status
- Ensure streamlit-ui service has the same environment variables
- Restart services after configuration changes
- Clear browser cache if needed

### Webhook processing issues
- Confirm webhook handlers have access to updated configuration
- Check that branch success detection logs show correct pattern matching
- Verify fix attempt tracking uses the new branch names

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `BRANCH_PREFIX_PIPELINE` | `fix/pipeline_` | Prefix for pipeline fix branches |
| `BRANCH_PREFIX_QUALITY` | `fix/sonarqube_` | Prefix for quality fix branches |
| `BRANCH_PREFIX_GENERAL` | `cicd-assistant/` | Prefix for general fix branches |

## Related Files

- `strands-agent/config.py` - Agent configuration with branch prefixes
- `streamlit-ui/config.py` - UI configuration for consistent branch recognition
- `strands-agent/agents/prompts.py` - Dynamic prompt generation with session-based guidelines
- `strands-agent/api/webhooks.py` - Enhanced branch pattern matching and session lookup
- `strands-agent/utils/branch_naming.py` - Utility functions for branch name generation and parsing
- `docker-compose.yml` - Environment variable mapping for containers
