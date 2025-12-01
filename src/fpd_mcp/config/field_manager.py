"""
Field Configuration Manager for Final Petition Decisions MCP

Manages loading and filtering of field configurations from YAML.
"""

import yaml
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class FieldManager:
    """Manages field configurations for FPD API responses"""

    def __init__(self, config_path: Path):
        """
        Initialize field manager with configuration file.

        Args:
            config_path: Path to field_configs.yaml file
        """
        self.config_path = config_path
        self.config_data: Dict[str, Any] = {}
        self.load_config()

    def load_config(self) -> None:
        """Load field configuration from YAML file with graceful fallback"""
        try:
            if not self.config_path.exists():
                raise FileNotFoundError(f"Field config file not found: {self.config_path}")

            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config_data = yaml.safe_load(f)

            logger.info(f"Loaded field configuration from {self.config_path}")
            logger.debug(f"Available field sets: {list(self.get_predefined_sets().keys())}")

        except (FileNotFoundError, yaml.YAMLError, Exception) as e:
            logger.error(f"Failed to load field configuration: {e}. Using defaults.")
            self.config_data = self._get_default_config()
            logger.info("Using default field configuration")

    def _get_default_config(self) -> Dict[str, Any]:
        """Provide default field configuration when config file fails to load"""
        return {
            "version": "1.0",
            "description": "Default configuration (fallback)",
            "predefined_sets": {
                "petitions_minimal": {
                    "description": "Essential fields for petition discovery",
                    "fields": [
                        "petitionDecisionRecordIdentifier",
                        "applicationNumberText",
                        "patentNumber",
                        "firstApplicantName",
                        "decisionTypeCodeDescriptionText",
                        "petitionMailDate",
                        "decisionDate",
                        "finalDecidingOfficeName"
                    ]
                },
                "petitions_balanced": {
                    "description": "Key fields for petition analysis",
                    "fields": [
                        "petitionDecisionRecordIdentifier",
                        "applicationNumberText",
                        "patentNumber",
                        "firstApplicantName",
                        "decisionTypeCodeDescriptionText",
                        "petitionMailDate",
                        "decisionDate",
                        "finalDecidingOfficeName",
                        "decisionPetitionTypeCode",
                        "decisionPetitionTypeCodeDescriptionText",
                        "groupArtUnitNumber",
                        "technologyCenter",
                        "businessEntityStatusCategory",
                        "prosecutionStatusCodeDescriptionText",
                        "inventionTitle",
                        "petitionIssueConsideredTextBag",
                        "ruleBag",
                        "statuteBag"
                    ]
                }
            },
            "context_settings": {
                "minimal_reduction_percentage": 95,
                "balanced_reduction_percentage": 80,
                "max_field_count_minimal": 8,
                "max_field_count_balanced": 18
            }
        }

    def get_predefined_sets(self) -> Dict[str, Dict]:
        """Get all predefined field sets"""
        return self.config_data.get("predefined_sets", {})

    def get_fields(self, field_set: str) -> List[str]:
        """
        Get fields for a specific field set.

        Args:
            field_set: Name of field set (e.g., 'petitions_minimal')

        Returns:
            List of field names
        """
        sets = self.get_predefined_sets()
        if field_set not in sets:
            available = list(sets.keys())
            raise ValueError(f"Field set '{field_set}' not found. Available: {available}")

        fields = sets[field_set].get("fields", [])
        logger.debug(f"Retrieved {len(fields)} fields for set '{field_set}'")
        return fields

    def get_context_settings(self) -> Dict[str, int]:
        """Get context management settings"""
        return self.config_data.get("context_settings", {})

    def filter_response(self, data: Dict[str, Any], field_set: str) -> Dict[str, Any]:
        """
        Filter API response to only include configured fields.

        Args:
            data: Raw API response data
            field_set: Name of field set to use for filtering

        Returns:
            Filtered response data
        """
        fields = self.get_fields(field_set)

        # FPD API uses 'petitionDecisionDataBag', not 'results'
        results_key = "petitionDecisionDataBag" if "petitionDecisionDataBag" in data else "results"
        count_key = "count" if "count" in data else "recordTotalQuantity"

        if results_key in data and isinstance(data[results_key], list):
            # Filter each result item
            filtered_results = []
            for item in data[results_key]:
                filtered_item = self._filter_item(item, fields)
                filtered_results.append(filtered_item)

            # Create filtered response using correct keys
            filtered_data = {
                results_key: filtered_results,  # Use petitionDecisionDataBag or results
                count_key: data.get(count_key, len(filtered_results)),
            }

            # Add recordStartNumber if present (for backwards compatibility)
            if "recordStartNumber" in data:
                filtered_data["recordStartNumber"] = data["recordStartNumber"]

            # Calculate context reduction based on actual character count
            original_data_sample = data[results_key][0] if data[results_key] else {}
            filtered_data_sample = filtered_results[0] if filtered_results else {}

            # Add context info
            filtered_data["context_info"] = {
                "fields_used": fields,
                "field_set": field_set,
                "original_field_count": len(original_data_sample.keys()) if original_data_sample else 0,
                "filtered_field_count": len(fields),
                "context_reduction": self._calculate_reduction(original_data_sample, filtered_data_sample)
            }

            logger.debug(f"Filtered response: {len(filtered_results)} items with {len(fields)} fields each")
            return filtered_data

        else:
            # Single item or unexpected format
            return self._filter_item(data, fields)

    def _filter_item(self, item: Dict[str, Any], fields: List[str]) -> Dict[str, Any]:
        """Filter a single item to only include specified fields"""
        if not isinstance(item, dict):
            return item

        filtered = {}
        for field in fields:
            if field in item:
                filtered[field] = item[field]

        return filtered

    def _calculate_reduction(self, original_data: Dict[str, Any], filtered_data: Dict[str, Any]) -> str:
        """Calculate actual character-based context reduction percentage"""
        import json

        try:
            # Calculate character count of JSON representations
            original_chars = len(json.dumps(original_data, separators=(',', ':')))
            filtered_chars = len(json.dumps(filtered_data, separators=(',', ':')))

            if original_chars == 0:
                return "0%"

            # Calculate actual context reduction
            reduction = ((original_chars - filtered_chars) / original_chars) * 100
            return f"{reduction:.0f}%"
        except Exception as e:
            logger.warning(f"Could not calculate character reduction: {e}")
            # Fallback to simple field count if character calculation fails
            return "N/A"
