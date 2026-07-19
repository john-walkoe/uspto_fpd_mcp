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
    from ..shared_secure_storage import get_uspto_api_key, resolve_api_key
except ImportError:
    try:
        from fpd_mcp.shared_secure_storage import get_uspto_api_key, resolve_api_key
    except ImportError:
        # Fallback for when secure storage is not available
        def get_uspto_api_key():
            return None

        def resolve_api_key(explicit_value, secure_storage_getter, env_var_name, default=None):
            if explicit_value:
                return explicit_value
            try:
                key = secure_storage_getter()
                if key:
                    return key
            except Exception:
                pass
            return os.getenv(env_var_name, default)


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # API Keys
    uspto_api_key: str
    mistral_api_key: Optional[str] = None

    # API Configuration
    api_base_url: str = "https://api.uspto.gov/api/v1/petition/decisions"

    # Default Search Limits
    default_minimal_limit: int = 50

    # Validation Limits
    max_search_limit: int = 200

    # File Paths
    field_config_path: Optional[Path] = None

    class Config:
        env_prefix = "FPD_MCP_"
        case_sensitive = False

    def __init__(self, **kwargs):
        # Resolve API keys BEFORE parent init using the shared 3-tier chain
        # (explicit kwarg -> unified secure storage -> environment variable).
        kwargs['uspto_api_key'] = resolve_api_key(
            kwargs.get('uspto_api_key'), get_uspto_api_key, 'USPTO_API_KEY', default=''
        )

        try:
            from ..shared_secure_storage import get_mistral_api_key
        except Exception:
            def get_mistral_api_key():
                return None
        kwargs['mistral_api_key'] = resolve_api_key(
            kwargs.get('mistral_api_key'), get_mistral_api_key, 'MISTRAL_API_KEY'
        )

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
