"""
Settings Configuration for Final Petition Decisions MCP

Manages environment variables and application settings.
"""

import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings

# Import unified secure storage functionality
try:
    from ..shared_secure_storage import get_uspto_api_key
except ImportError:
    try:
        from fpd_mcp.shared_secure_storage import get_uspto_api_key
    except ImportError:
        # Fallback for when secure storage is not available
        def get_uspto_api_key():
            return None


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # API Keys
    uspto_api_key: str
    mistral_api_key: Optional[str] = None

    # Server Configuration
    log_level: str = "INFO"

    # API Configuration
    api_base_url: str = "https://api.uspto.gov/api/v1/petition/decisions"
    api_timeout: int = 30
    max_retries: int = 3

    # Context Management
    max_minimal_results: int = 100
    max_balanced_results: int = 20
    max_document_results: int = 50

    # Default Search Limits
    default_minimal_limit: int = 50
    default_balanced_limit: int = 10
    default_document_limit: int = 50

    # Validation Limits
    max_applicant_name_length: int = 200
    max_petition_id_length: int = 100
    max_search_limit: int = 200
    min_search_limit: int = 1

    # Application Number Validation
    min_application_number_length: int = 6
    max_application_number_length: int = 20

    # Patent Number Validation
    min_patent_number_digits: int = 7
    max_patent_number_digits: int = 10

    # Rate Limiting
    default_rate_limit_tokens: int = 10
    default_rate_limit_refill: float = 1.0

    # Network Settings
    default_timeout: int = 30

    # File Paths
    field_config_path: Optional[Path] = None

    class Config:
        env_prefix = "FPD_MCP_"
        case_sensitive = False

    def __init__(self, **kwargs):
        # Try to get USPTO API key from unified secure storage BEFORE parent init
        if 'uspto_api_key' not in kwargs or not kwargs.get('uspto_api_key'):
            try:
                secure_key = get_uspto_api_key()
                if secure_key:
                    kwargs['uspto_api_key'] = secure_key
            except Exception:
                # Fall back to environment variable if secure storage fails
                pass
            
            # Check for USPTO_API_KEY if still not provided
            if 'uspto_api_key' not in kwargs or not kwargs.get('uspto_api_key'):
                kwargs['uspto_api_key'] = os.getenv('USPTO_API_KEY', '')

        # Try to get Mistral API key from unified secure storage BEFORE parent init
        if 'mistral_api_key' not in kwargs or not kwargs.get('mistral_api_key'):
            try:
                from ..shared_secure_storage import get_mistral_api_key
                secure_key = get_mistral_api_key()
                if secure_key:
                    kwargs['mistral_api_key'] = secure_key
            except Exception:
                # Fall back to environment variable if secure storage fails
                pass
            
            # Check for MISTRAL_API_KEY if still not provided
            if 'mistral_api_key' not in kwargs or not kwargs.get('mistral_api_key'):
                kwargs['mistral_api_key'] = os.getenv('MISTRAL_API_KEY')

        super().__init__(**kwargs)

        # Set default field config path if not provided
        if self.field_config_path is None:
            # Default to field_configs.yaml in project root
            current_file = Path(__file__)
            project_root = current_file.parent.parent.parent.parent
            self.field_config_path = project_root / "field_configs.yaml"

    @property
    def field_config_exists(self) -> bool:
        """Check if field configuration file exists"""
        return self.field_config_path and self.field_config_path.exists()
