"""
Branch Naming Utilities
Implements the agreed branch naming strategy: fix/[type]_[full_session_id]_[date]
"""
import os
import re
from datetime import datetime
from typing import Dict, Optional


def normalize_session_id_for_branch(session_id: str) -> str:
    """
    Convert session ID to format suitable for branch names.
    Removes hyphens to create a 32-character string.
    
    Args:
        session_id: Full UUID like 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
    
    Returns:
        Normalized ID like 'a1b2c3d4e5f67890abcdef1234567890'
    """
    normalized = session_id.replace('-', '')
    
    # Validate length
    if len(normalized) != 32:
        raise ValueError(f"Invalid session ID format. Expected 32 chars after normalization, got {len(normalized)}")
    
    # Validate hex characters
    if not re.match(r'^[a-f0-9]{32}$', normalized):
        raise ValueError(f"Invalid session ID format. Must be hexadecimal: {normalized}")
    
    return normalized


def denormalize_session_id_from_branch(normalized_id: str) -> str:
    """
    Convert normalized session ID back to full UUID format.
    
    Args:
        normalized_id: 32-char string like 'a1b2c3d4e5f67890abcdef1234567890'
    
    Returns:
        Full UUID like 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
    """
    if len(normalized_id) != 32:
        raise ValueError(f"Invalid normalized session ID length: {len(normalized_id)}")
    
    if not re.match(r'^[a-f0-9]{32}$', normalized_id):
        raise ValueError(f"Invalid normalized session ID format: {normalized_id}")
    
    return f"{normalized_id[:8]}-{normalized_id[8:12]}-{normalized_id[12:16]}-{normalized_id[16:20]}-{normalized_id[20:]}"


def generate_branch_name(session_id: str, branch_type: str = "pipeline") -> str:
    """
    Generate branch name following the agreed format: fix/[type]_[full_session_id]_[date]
    
    Args:
        session_id: Full session UUID
        branch_type: 'pipeline' or 'quality'
    
    Returns:
        Branch name like 'fix/pipeline_a1b2c3d4e5f67890abcdef1234567890_20250817'
    """
    # Get prefix from environment
    if branch_type == "pipeline":
        prefix = os.getenv("BRANCH_PREFIX_PIPELINE", "fix/pipeline_")
    elif branch_type == "quality":
        prefix = os.getenv("BRANCH_PREFIX_QUALITY", "fix/quality_")
    else:
        raise ValueError(f"Invalid branch type: {branch_type}. Must be 'pipeline' or 'quality'")
    
    # Normalize session ID (remove hyphens)
    normalized_session_id = normalize_session_id_for_branch(session_id)
    
    # Get current date
    date_format = os.getenv("DATE_FORMAT", "%Y%m%d")
    current_date = datetime.now().strftime(date_format)
    
    # Build branch name: fix/pipeline_a1b2c3d4e5f67890abcdef1234567890_20250817
    branch_name = f"{prefix}{normalized_session_id}_{current_date}"
    
    return branch_name


def extract_session_id_from_branch(branch_name: str) -> str:
    """
    Extract session ID from branch name following our agreed format.
    
    Args:
        branch_name: Branch like 'fix/pipeline_a1b2c3d4e5f67890abcdef1234567890_20250817'
    
    Returns:
        Full session UUID like 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
    """
    if not is_fix_branch(branch_name):
        raise ValueError(f"Branch does not follow expected format: {branch_name}")
    
    # Remove prefix
    if branch_name.startswith("fix/pipeline_"):
        content = branch_name[len("fix/pipeline_"):]
    elif branch_name.startswith("fix/quality_"):
        content = branch_name[len("fix/quality_"):]
    else:
        raise ValueError(f"Unknown branch prefix: {branch_name}")
    
    # Split by underscore to separate session_id and date
    # Expected: a1b2c3d4e5f67890abcdef1234567890_20250817
    parts = content.split("_")
    if len(parts) < 2:
        raise ValueError(f"Invalid branch format - missing date: {branch_name}")
    
    # First part should be the 32-character session ID
    normalized_session_id = parts[0]
    if len(normalized_session_id) != 32:
        raise ValueError(f"Invalid session ID length in branch: {normalized_session_id}")
    
    # Validate session ID format
    if not re.match(r'^[a-f0-9]{32}$', normalized_session_id):
        raise ValueError(f"Invalid session ID format in branch: {normalized_session_id}")
    
    # Convert back to full UUID format
    return denormalize_session_id_from_branch(normalized_session_id)


def extract_branch_info(branch_name: str) -> Dict[str, str]:
    """
    Extract all information from a fix branch name.
    
    Args:
        branch_name: Branch like 'fix/pipeline_a1b2c3d4e5f67890abcdef1234567890_20250817'
    
    Returns:
        Dict with keys: session_id, branch_type, date, normalized_session_id
    """
    if not is_fix_branch(branch_name):
        raise ValueError(f"Not a fix branch: {branch_name}")
    
    # Determine branch type
    branch_type = get_branch_type(branch_name)
    
    # Extract session ID
    session_id = extract_session_id_from_branch(branch_name)
    
    # Extract date
    if branch_name.startswith("fix/pipeline_"):
        content = branch_name[len("fix/pipeline_"):]
    else:  # fix/quality_
        content = branch_name[len("fix/quality_"):]
    
    parts = content.split("_")
    date_str = parts[1] if len(parts) > 1 else "unknown"
    
    return {
        "session_id": session_id,
        "branch_type": branch_type,
        "date": date_str,
        "normalized_session_id": normalize_session_id_for_branch(session_id)
    }


def is_fix_branch(branch_name: str) -> bool:
    """Check if a branch follows our fix branch naming convention."""
    return branch_name.startswith(("fix/pipeline_", "fix/quality_"))


def get_branch_type(branch_name: str) -> str:
    """
    Determine the type of fix branch.
    
    Returns:
        'pipeline' or 'quality'
    """
    if branch_name.startswith("fix/pipeline_"):
        return "pipeline"
    elif branch_name.startswith("fix/quality_"):
        return "quality"
    else:
        raise ValueError(f"Not a fix branch: {branch_name}")


def get_branch_naming_examples() -> Dict[str, str]:
    """Get examples of branch names for documentation/testing."""
    example_session_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    
    return {
        "pipeline": generate_branch_name(example_session_id, "pipeline"),
        "quality": generate_branch_name(example_session_id, "quality"),
        "session_id": example_session_id,
        "normalized_id": normalize_session_id_for_branch(example_session_id)
    }


def validate_branch_format(branch_name: str) -> bool:
    """
    Validate if a branch name follows our exact format.
    
    Returns:
        True if valid, False otherwise
    """
    try:
        if not is_fix_branch(branch_name):
            return False
        
        # Try to extract session ID - will raise exception if invalid
        extract_session_id_from_branch(branch_name)
        return True
    except Exception:
        return False


def safe_extract_session_id(branch_name: str) -> Optional[str]:
    """
    Safely extract session ID from branch name without raising exceptions.
    
    Returns:
        Session UUID or None if extraction fails
    """
    try:
        return extract_session_id_from_branch(branch_name)
    except Exception:
        return None


if __name__ == "__main__":
    # Demo/test the branch naming utilities
    examples = get_branch_naming_examples()
    print("Branch Naming Examples:")
    for key, value in examples.items():
        print(f"  {key}: {value}")
    
    # Test round-trip conversion
    original_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    pipeline_branch = generate_branch_name(original_id, "pipeline")
    quality_branch = generate_branch_name(original_id, "quality")
    
    print(f"\nRound-trip test:")
    print(f"Original ID: {original_id}")
    print(f"Pipeline Branch: {pipeline_branch}")
    print(f"Quality Branch: {quality_branch}")
    print(f"Extracted from Pipeline: {extract_session_id_from_branch(pipeline_branch)}")
    print(f"Extracted from Quality: {extract_session_id_from_branch(quality_branch)}")
    print(f"Round-trip successful: {original_id == extract_session_id_from_branch(pipeline_branch)}")
