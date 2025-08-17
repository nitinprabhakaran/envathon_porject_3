"""
Branch Naming Utilities for Webhook Handler
Minimal implementation of branch naming functions needed by webhook-handler
"""
import re
from typing import Dict, Optional


def normalize_session_id_for_branch(session_id: str) -> str:
    """Convert session ID to format suitable for branch names."""
    normalized = session_id.replace('-', '')
    if len(normalized) != 32:
        raise ValueError(f"Invalid session ID format. Expected 32 chars after normalization, got {len(normalized)}")
    if not re.match(r'^[a-f0-9]{32}$', normalized):
        raise ValueError(f"Invalid session ID format. Must be hexadecimal: {normalized}")
    return normalized


def denormalize_session_id_from_branch(normalized_id: str) -> str:
    """Convert normalized session ID back to full UUID format."""
    if len(normalized_id) != 32:
        raise ValueError(f"Invalid normalized session ID length: {len(normalized_id)}")
    if not re.match(r'^[a-f0-9]{32}$', normalized_id):
        raise ValueError(f"Invalid normalized session ID format: {normalized_id}")
    return f"{normalized_id[:8]}-{normalized_id[8:12]}-{normalized_id[12:16]}-{normalized_id[16:20]}-{normalized_id[20:]}"


def extract_branch_info(branch_name: str) -> Dict[str, str]:
    """
    Extract information from a fix branch name.
    
    Args:
        branch_name: Branch name like 'fix/pipeline_a1b2c3d4e5f67890abcdef1234567890_20250817'
    
    Returns:
        Dict with 'type', 'session_id', 'date', 'normalized_session_id'
    """
    if not is_fix_branch(branch_name):
        return {
            "type": "unknown",
            "session_id": None,
            "date": None,
            "normalized_session_id": None
        }
    
    # Pattern: fix/[type]_[32_char_session_id]_[date]
    pattern = r'fix/([a-z]+)_([a-f0-9]{32})_(\d{8})'
    match = re.match(pattern, branch_name)
    
    if not match:
        return {
            "type": "unknown",
            "session_id": None,
            "date": None,
            "normalized_session_id": None
        }
    
    fix_type, normalized_session_id, date = match.groups()
    full_session_id = denormalize_session_id_from_branch(normalized_session_id)
    
    return {
        "type": fix_type,
        "session_id": full_session_id,
        "date": date,
        "normalized_session_id": normalized_session_id
    }


def is_fix_branch(branch_name: str) -> bool:
    """Check if branch name follows fix branch naming convention."""
    return bool(re.match(r'fix/[a-z]+_[a-f0-9]{32}_\d{8}', branch_name))


def get_branch_type(branch_name: str) -> str:
    """Extract the fix type from a fix branch name."""
    if not is_fix_branch(branch_name):
        return "unknown"
    
    # Extract type from fix/[type]_...
    match = re.match(r'fix/([a-z]+)_', branch_name)
    return match.group(1) if match else "unknown"


def extract_session_id_from_branch(branch_name: str) -> Optional[str]:
    """
    Extract session ID from a fix branch name.
    
    Args:
        branch_name: Branch name like 'fix/pipeline_a1b2c3d4e5f67890abcdef1234567890_20250817'
    
    Returns:
        Full session ID like 'a1b2c3d4-e5f6-7890-abcd-ef1234567890' or None
    """
    info = extract_branch_info(branch_name)
    return info.get("session_id")


def safe_extract_session_id(branch_name: str) -> Optional[str]:
    """
    Safely extract session ID from branch name, returning None if extraction fails.
    """
    try:
        return extract_session_id_from_branch(branch_name)
    except Exception:
        return None
