#!/usr/bin/env python3
"""
Article Frontmatter Schema Validator

Validates article frontmatter against the defined schema.
Ensures required fields are present and content_type values are valid.
"""

import json
import sys
from pathlib import Path

# Schema definition
REQUIRED_FIELDS = {
    'title': str,
    'date': str,
    'categories': list,
    'author': str,
    'draft': bool,
}

OPTIONAL_FIELDS = {
    'journalist_note': str,
    'content_type': str,
    'editorial_reviewed': bool,
    'author_title': str,
    'author_image': str,
    'author_bio': str,
    'tags': list,
    'keywords': list,
    'lastmod': str,
}

VALID_CONTENT_TYPES = ['article', 'analysis', 'opinion']


def validate_article(article_dict):
    """
    Validate an article's frontmatter.
    
    Returns: (is_valid: bool, errors: list[str])
    """
    errors = []
    
    # Check required fields
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in article_dict:
            errors.append(f"Missing required field: {field}")
        elif not isinstance(article_dict[field], expected_type):
            errors.append(f"Field '{field}' must be {expected_type.__name__}, got {type(article_dict[field]).__name__}")
    
    # Check optional fields if present
    for field, expected_type in OPTIONAL_FIELDS.items():
        if field in article_dict:
            if not isinstance(article_dict[field], expected_type):
                errors.append(f"Field '{field}' must be {expected_type.__name__}, got {type(article_dict[field]).__name__}")
    
    # Validate content_type enum
    if 'content_type' in article_dict:
        ct = article_dict['content_type']
        if ct not in VALID_CONTENT_TYPES:
            errors.append(f"Invalid content_type: '{ct}'. Must be one of: {', '.join(VALID_CONTENT_TYPES)}")
    
    # Categories should not be empty
    if 'categories' in article_dict and isinstance(article_dict['categories'], list):
        if not article_dict['categories']:
            errors.append("Field 'categories' cannot be empty")
    
    return len(errors) == 0, errors


def validate_and_report(article_dict, article_title=""):
    """
    Validate and print results.
    """
    is_valid, errors = validate_article(article_dict)
    
    if is_valid:
        print(f"✓ Schema valid: {article_title}")
        return True
    else:
        print(f"✗ Schema errors in '{article_title}':")
        for error in errors:
            print(f"  - {error}")
        return False


if __name__ == '__main__':
    # Example usage
    test_article = {
        'title': 'Test Article',
        'date': '2026-03-23T10:00:00+00:00',
        'categories': ['Test'],
        'author': 'Author Name',
        'draft': False,
        'content_type': 'analysis',
        'journalist_note': 'Some note',
    }
    
    validate_and_report(test_article, 'Test Article')
