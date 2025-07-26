import re
import hashlib
from typing import Dict, Any, List, Optional
from strands import tool
from loguru import logger

# Import GitLab tools for internal use
from .gitlab_tools import get_pipeline_jobs, get_job_logs

@tool
async def analyze_pipeline_logs(
    pipeline_id: str,
    job_name: Optional[str] = None,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Analyze pipeline logs to extract error patterns and root causes
    
    Args:
        pipeline_id: The pipeline ID to analyze
        job_name: Specific job name to analyze (optional)
        project_id: The project ID (if not provided, will try to get from context)
    
    Returns:
        Analysis including failed jobs, error patterns, and root cause candidates
    """
    # Get all jobs in the pipeline
    jobs = await get_pipeline_jobs(pipeline_id, project_id)
    
    if isinstance(jobs, list) and len(jobs) > 0 and "error" in jobs[0]:
        return {"error": jobs[0]["error"]}
    
    # Filter failed jobs
    failed_jobs = [job for job in jobs if job.get("status") == "failed"]
    
    if job_name:
        failed_jobs = [job for job in failed_jobs if job.get("name") == job_name]
    
    analysis = {
        "pipeline_id": pipeline_id,
        "total_jobs": len(jobs),
        "failed_jobs": [],
        "error_patterns": [],
        "root_cause_candidates": []
    }
    
    # Analyze each failed job
    for job in failed_jobs:
        job_logs = await get_job_logs(str(job["id"]), project_id)
        
        if "Error:" in job_logs:
            # Extract error information
            error_lines = []
            lines = job_logs.split('\n')
            
            for i, line in enumerate(lines):
                if any(keyword in line.lower() for keyword in ['error', 'failed', 'exception', 'fatal']):
                    # Get context: 3 lines before and after
                    start = max(0, i - 3)
                    end = min(len(lines), i + 4)
                    context = lines[start:end]
                    error_lines.append({
                        "line_number": i,
                        "line": line,
                        "context": '\n'.join(context)
                    })
            
            job_analysis = {
                "job_id": job["id"],
                "job_name": job["name"],
                "stage": job["stage"],
                "status": job["status"],
                "error_count": len(error_lines),
                "errors": error_lines[:5],  # Limit to first 5 errors
                "duration": job.get("duration", 0)
            }
            
            analysis["failed_jobs"].append(job_analysis)
            
            # Extract common patterns
            patterns = _extract_error_patterns(job_logs)
            analysis["error_patterns"].extend(patterns)
    
    # Deduplicate patterns
    seen_patterns = set()
    unique_patterns = []
    for pattern in analysis["error_patterns"]:
        if pattern["signature"] not in seen_patterns:
            seen_patterns.add(pattern["signature"])
            unique_patterns.append(pattern)
    
    analysis["error_patterns"] = unique_patterns
    
    # Identify root cause candidates
    analysis["root_cause_candidates"] = _identify_root_causes(analysis["error_patterns"])
    
    return analysis

@tool
async def extract_error_signature(logs: str) -> str:
    """Extract a unique signature from error logs for similarity matching
    
    Args:
        logs: The log content to analyze
    
    Returns:
        A unique error signature string
    """
    # Normalize the logs
    normalized = logs
    
    # Remove timestamps
    normalized = re.sub(r'\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[\.\d]*[Z]?', '', normalized)
    normalized = re.sub(r'\[\d{2}:\d{2}:\d{2}\]', '', normalized)
    
    # Remove UUIDs
    normalized = re.sub(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', 'UUID', normalized)
    
    # Remove hex values
    normalized = re.sub(r'0x[a-f0-9]+', '0xHEX', normalized)
    
    # Remove numbers that look like IDs or counts
    normalized = re.sub(r'\b\d{4,}\b', 'NUM', normalized)
    
    # Remove file paths but keep file names
    normalized = re.sub(r'([/\\][\w\-/\\]+)+\/([\w\-\.]+)', r'\2', normalized)
    
    # Extract key error lines
    error_lines = []
    for line in normalized.split('\n'):
        line = line.strip()
        if any(keyword in line.lower() for keyword in ['error:', 'failed:', 'exception:', 'fatal:', 'panic:']):
            # Clean the line further
            line = re.sub(r'\s+', ' ', line)  # Normalize whitespace
            line = re.sub(r'line \d+', 'line N', line)  # Normalize line numbers
            error_lines.append(line)
    
    # Take top 5 most relevant error lines
    if error_lines:
        signature_lines = error_lines[:5]
    else:
        # Fallback: take lines with common error indicators
        all_lines = [line.strip() for line in normalized.split('\n') if line.strip()]
        signature_lines = [line for line in all_lines if len(line) > 20][:5]
    
    # Create signature
    signature_text = ' | '.join(signature_lines)
    signature_hash = hashlib.sha256(signature_text.encode()).hexdigest()[:12]
    
    return f"{signature_hash}:{signature_text[:200]}"

@tool
async def intelligent_log_truncation(logs: str, max_tokens: int = 4000) -> str:
    """Intelligently truncate logs while preserving error context
    
    Args:
        logs: The full log content
        max_tokens: Maximum number of tokens (approximately 4 chars per token)
    
    Returns:
        Truncated logs preserving the most important information
    """
    lines = logs.split('\n')
    
    # Categorize lines
    error_sections = []
    warning_sections = []
    summary_sections = []
    normal_lines = []
    
    # Find error sections
    for i, line in enumerate(lines):
        if any(keyword in line.lower() for keyword in ['error:', 'failed:', 'exception:', 'fatal:']):
            # Get context: 5 lines before and after
            start = max(0, i - 5)
            end = min(len(lines), i + 6)
            section = lines[start:end]
            error_sections.append({
                "start": start,
                "end": end,
                "lines": section,
                "priority": 1
            })
        elif any(keyword in line.lower() for keyword in ['warning:', 'warn:']):
            start = max(0, i - 2)
            end = min(len(lines), i + 3)
            section = lines[start:end]
            warning_sections.append({
                "start": start,
                "end": end,
                "lines": section,
                "priority": 2
            })
        elif any(keyword in line.lower() for keyword in ['summary:', 'result:', 'finished:', 'completed:']):
            summary_sections.append({
                "line": line,
                "index": i,
                "priority": 3
            })
    
    # Build truncated output
    output_lines = []
    
    # Add header
    output_lines.append("=== INTELLIGENTLY TRUNCATED LOG ===")
    output_lines.append(f"Original: {len(lines)} lines, Truncated to fit {max_tokens} tokens")
    output_lines.append("")
    
    # Add error sections first
    if error_sections:
        output_lines.append("=== ERROR SECTIONS ===")
        # Deduplicate overlapping sections
        added_ranges = []
        for section in error_sections[:10]:  # Max 10 error sections
            range_key = (section["start"], section["end"])
            if range_key not in added_ranges:
                added_ranges.append(range_key)
                output_lines.extend(section["lines"])
                output_lines.append("---")
    
    # Add warnings if space allows
    current_size = sum(len(line) for line in output_lines)
    if current_size < max_tokens * 3 and warning_sections:  # Reserve some space
        output_lines.append("\n=== WARNING SECTIONS ===")
        for section in warning_sections[:5]:
            output_lines.extend(section["lines"])
            output_lines.append("---")
    
    # Add summary if space allows
    current_size = sum(len(line) for line in output_lines)
    if current_size < max_tokens * 3.5 and summary_sections:
        output_lines.append("\n=== SUMMARY SECTIONS ===")
        for section in summary_sections[:5]:
            output_lines.append(section["line"])
    
    # Final truncation if still too long
    result = '\n'.join(output_lines)
    if len(result) > max_tokens * 4:
        result = result[:max_tokens * 4] + "\n... [TRUNCATED]"
    
    return result

def _extract_error_patterns(logs: str) -> List[Dict[str, Any]]:
    """Extract common error patterns from logs"""
    patterns = []
    
    # Common CI/CD error patterns
    pattern_matchers = [
        # Dependency errors
        (r'npm ERR!.*', 'npm_error', 'dependency'),
        (r'ERROR: (Could not find a version|No matching distribution)', 'pip_error', 'dependency'),
        (r'fatal: repository .* not found', 'git_error', 'repository'),
        (r'docker: (command not found|Cannot connect)', 'docker_error', 'infrastructure'),
        (r'Permission denied', 'permission_error', 'infrastructure'),
        (r'Module .* not found', 'module_error', 'dependency'),
        (r'SyntaxError:', 'syntax_error', 'code'),
        (r'connection refused', 'connection_error', 'infrastructure'),
        (r'timeout', 'timeout_error', 'infrastructure'),
        (r'out of memory', 'memory_error', 'infrastructure'),
    ]
    
    for pattern, error_type, category in pattern_matchers:
        matches = re.findall(pattern, logs, re.IGNORECASE)
        if matches:
            patterns.append({
                "pattern": pattern,
                "type": error_type,
                "category": category,
                "occurrences": len(matches),
                "signature": hashlib.md5(error_type.encode()).hexdigest()[:8],
                "examples": matches[:3]
            })
    
    return patterns

def _identify_root_causes(error_patterns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Identify likely root causes from error patterns"""
    root_causes = []
    
    # Group by category
    categories = {}
    for pattern in error_patterns:
        cat = pattern["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(pattern)
    
    # Analyze each category
    for category, patterns in categories.items():
        total_occurrences = sum(p["occurrences"] for p in patterns)
        
        if category == "dependency":
            root_causes.append({
                "category": "dependency",
                "description": "Dependency resolution or installation issues",
                "confidence": min(0.9, total_occurrences * 0.1),
                "patterns": patterns,
                "suggested_fixes": [
                    "Clear dependency cache and reinstall",
                    "Check for version conflicts",
                    "Verify package registry accessibility"
                ]
            })
        elif category == "infrastructure":
            root_causes.append({
                "category": "infrastructure",
                "description": "Infrastructure or environment configuration issues",
                "confidence": min(0.85, total_occurrences * 0.15),
                "patterns": patterns,
                "suggested_fixes": [
                    "Check service availability",
                    "Verify credentials and permissions",
                    "Review resource limits"
                ]
            })
        elif category == "code":
            root_causes.append({
                "category": "code",
                "description": "Code syntax or logic errors",
                "confidence": 0.95,
                "patterns": patterns,
                "suggested_fixes": [
                    "Review recent code changes",
                    "Run linting and static analysis",
                    "Check for missing imports"
                ]
            })
    
    # Sort by confidence
    root_causes.sort(key=lambda x: x["confidence"], reverse=True)
    
    return root_causes