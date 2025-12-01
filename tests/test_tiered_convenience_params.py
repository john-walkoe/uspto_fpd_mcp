"""
Test script for tiered convenience parameters implementation in FPD MCP.

This script tests that:
1. The _build_convenience_query helper function works correctly
2. Different tool types get appropriate parameter sets
3. Date validation works properly
4. The tiered approach respects progressive disclosure principles
5. Parameter validation and error handling work correctly
6. Query building produces correct results
"""

import sys
import os
import re
from datetime import datetime
from typing import Optional, Dict, Any, Tuple


def validate_date_range(date_str: str) -> str:
    """Validate date string in YYYY-MM-DD format"""
    if not date_str:
        return None
    
    # Remove whitespace
    clean_date = date_str.strip()
    
    # If empty after stripping, return None
    if not clean_date:
        return None
    
    # Check format YYYY-MM-DD
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', clean_date):
        raise ValueError("Date must be in YYYY-MM-DD format (e.g., '2024-01-01')")
    
    # Validate actual date values
    try:
        datetime.strptime(clean_date, '%Y-%m-%d')
    except ValueError:
        raise ValueError("Invalid date. Please check year, month, and day values.")
    
    # Check reasonable date range (1990 to current year + 5)
    year = int(clean_date[:4])
    current_year = datetime.now().year
    if year < 1990 or year > current_year + 5:
        raise ValueError(f"Date year must be between 1990 and {current_year + 5}")
    
    return clean_date


def validate_string_param(param_name: str, param_value: str, max_length: int = 200) -> str:
    """Validate string parameter input"""
    if not param_value:
        return None
    
    # Trim whitespace
    clean_value = param_value.strip()
    
    if not clean_value:
        return None
    
    # Check length limits
    if len(clean_value) > max_length:
        raise ValueError(f"{param_name} too long. Maximum {max_length} characters.")
    
    # Check for suspicious characters that might indicate injection attempts
    if re.search(r'[<>"\'\\\\/\x00-\x1f]', clean_value):
        raise ValueError(f"{param_name} contains invalid characters.")
    
    return clean_value


def validate_application_number(app_number: str) -> str:
    """Validate and clean USPTO application number format"""
    if not app_number:
        return None
    
    # Remove whitespace and clean format
    clean_number = app_number.strip().replace("/", "").replace(" ", "")
    
    if not clean_number:
        return None
    
    # Basic length validation (USPTO application numbers are typically 8 digits)
    if len(clean_number) < 6 or len(clean_number) > 10:
        raise ValueError("Application number should be 6-10 digits")
    
    # Check if all characters are digits
    if not clean_number.isdigit():
        raise ValueError("Application number should contain only digits")
    
    return clean_number


def _build_convenience_query(
    query: str = "",
    # Core Identity & Party
    applicant_name: Optional[str] = None,
    application_number: Optional[str] = None,
    patent_number: Optional[str] = None,
    # Decision Filters  
    decision_type: Optional[str] = None,
    deciding_office: Optional[str] = None,
    # Date Ranges
    petition_date_start: Optional[str] = None,
    petition_date_end: Optional[str] = None,
    decision_date_start: Optional[str] = None,
    decision_date_end: Optional[str] = None,
    # Balanced tier additional parameters
    petition_type_code: Optional[str] = None,
    art_unit: Optional[str] = None,
    technology_center: Optional[str] = None,
    prosecution_status: Optional[str] = None,
    entity_status: Optional[str] = None,
    # Control which parameters are allowed
    allow_balanced_params: bool = False
) -> Tuple[str, Dict[str, Any]]:
    """Build query string from convenience parameters
    
    Returns:
        tuple: (final_query_string, convenience_parameters_used)
    """
    try:
        # Build query from convenience parameters
        query_parts = []
        convenience_params_used = {}
        
        # Include base query if provided
        if query and query.strip():
            query_parts.append(f"({query})")
            convenience_params_used["base_query"] = query
        
        # Add minimal tier convenience parameters
        if applicant_name:
            validated_name = validate_string_param("applicant_name", applicant_name)
            if validated_name:
                query_parts.append(f'firstApplicantName:"{validated_name}"')
                convenience_params_used["applicant_name"] = validated_name
        
        if application_number:
            validated_app = validate_application_number(application_number)
            if validated_app:
                query_parts.append(f"applicationNumberText:{validated_app}")
                convenience_params_used["application_number"] = validated_app
        
        if patent_number:
            validated_patent = validate_string_param("patent_number", patent_number, 15)
            if validated_patent:
                query_parts.append(f"patentNumber:{validated_patent}")
                convenience_params_used["patent_number"] = validated_patent
        
        if decision_type:
            validated_decision = validate_string_param("decision_type", decision_type, 50)
            if validated_decision:
                query_parts.append(f"decisionTypeCodeDescriptionText:{validated_decision}")
                convenience_params_used["decision_type"] = validated_decision
        
        if deciding_office:
            validated_office = validate_string_param("deciding_office", deciding_office)
            if validated_office:
                query_parts.append(f'finalDecidingOfficeName:"{validated_office}"')
                convenience_params_used["deciding_office"] = validated_office
        
        # Date range filters
        if petition_date_start or petition_date_end:
            start = validate_date_range(petition_date_start) if petition_date_start else "*"
            end = validate_date_range(petition_date_end) if petition_date_end else "*"
            if start != "*" or end != "*":
                query_parts.append(f"petitionMailDate:[{start} TO {end}]")
                convenience_params_used["petition_date_range"] = f"{start} TO {end}"
        
        if decision_date_start or decision_date_end:
            start = validate_date_range(decision_date_start) if decision_date_start else "*"
            end = validate_date_range(decision_date_end) if decision_date_end else "*"
            if start != "*" or end != "*":
                query_parts.append(f"decisionDate:[{start} TO {end}]")
                convenience_params_used["decision_date_range"] = f"{start} TO {end}"
        
        # Add balanced tier additional parameters (only if allowed)
        if allow_balanced_params:
            if petition_type_code:
                validated_type = validate_string_param("petition_type_code", petition_type_code, 10)
                if validated_type:
                    query_parts.append(f"decisionPetitionTypeCode:{validated_type}")
                    convenience_params_used["petition_type_code"] = validated_type
            
            if art_unit:
                validated_art_unit = validate_string_param("art_unit", art_unit, 10)
                if validated_art_unit:
                    query_parts.append(f"groupArtUnitNumber:{validated_art_unit}")
                    convenience_params_used["art_unit"] = validated_art_unit
            
            if technology_center:
                validated_tc = validate_string_param("technology_center", technology_center, 10)
                if validated_tc:
                    query_parts.append(f"technologyCenter:{validated_tc}")
                    convenience_params_used["technology_center"] = validated_tc
            
            if prosecution_status:
                validated_status = validate_string_param("prosecution_status", prosecution_status)
                if validated_status:
                    query_parts.append(f'prosecutionStatusCodeDescriptionText:"{validated_status}"')
                    convenience_params_used["prosecution_status"] = validated_status
            
            if entity_status:
                validated_entity = validate_string_param("entity_status", entity_status, 50)
                if validated_entity:
                    query_parts.append(f'businessEntityStatusCategory:"{validated_entity}"')
                    convenience_params_used["entity_status"] = validated_entity
        else:
            # Check if balanced-only parameters were provided but not allowed
            balanced_only_params = [petition_type_code, art_unit, technology_center, prosecution_status, entity_status]
            provided_balanced_params = [p for p in balanced_only_params if p is not None]
            if provided_balanced_params:
                raise ValueError(
                    "Parameters petition_type_code, art_unit, technology_center, prosecution_status, "
                    "and entity_status are only available in fpd_search_petitions_balanced. "
                    "Use fpd_search_petitions_balanced for advanced filtering."
                )
        
        # Validate we have at least one search criterion
        if not query_parts:
            raise ValueError(
                "Must provide either 'query' parameter or at least one convenience parameter"
            )
        
        # Combine all query parts with AND
        final_query = " AND ".join(query_parts)
        
        return final_query, convenience_params_used
        
    except Exception as e:
        raise ValueError(f"Query building failed: {str(e)}")


def test_date_validation():
    """Test date validation function"""
    print("Testing date validation...")
    
    # Valid dates
    assert validate_date_range("2024-01-01") == "2024-01-01"
    assert validate_date_range("2023-12-31") == "2023-12-31"
    assert validate_date_range("") is None
    assert validate_date_range("   ") is None
    assert validate_date_range(None) is None
    
    # Invalid formats
    try:
        validate_date_range("2024/01/01")
        assert False, "Should have failed on invalid format"
    except ValueError as e:
        assert "YYYY-MM-DD format" in str(e)
    
    try:
        validate_date_range("2024-13-01")
        assert False, "Should have failed on invalid month"
    except ValueError:
        pass  # Expected
    
    # Invalid date range (too old)
    try:
        validate_date_range("1980-01-01")
        assert False, "Should have failed on too old date"
    except ValueError as e:
        assert "between 1990 and" in str(e)
    
    print("Date validation tests passed")


def test_string_validation():
    """Test string parameter validation"""
    print("Testing string validation...")
    
    # Valid strings
    assert validate_string_param("test", "Apple Inc.") == "Apple Inc."
    assert validate_string_param("test", "  Valid Name  ") == "Valid Name"
    assert validate_string_param("test", "") is None
    assert validate_string_param("test", None) is None
    
    # Invalid characters
    try:
        validate_string_param("test", "Invalid<script>")
        assert False, "Should have failed on invalid characters"
    except ValueError:
        pass  # Expected
    
    # Too long
    try:
        validate_string_param("test", "x" * 201)
        assert False, "Should have failed on length"
    except ValueError as e:
        assert "too long" in str(e)
    
    print("String validation tests passed")


def test_application_number_validation():
    """Test application number validation and cleaning"""
    print("Testing application number validation...")
    
    # Valid formats
    assert validate_application_number("17896175") == "17896175"
    assert validate_application_number("17/896175") == "17896175"
    assert validate_application_number("  17 896 175  ") == "17896175"
    assert validate_application_number("") is None
    assert validate_application_number(None) is None
    
    # Invalid formats
    try:
        validate_application_number("12345")  # Too short
        assert False, "Should have failed on too short"
    except ValueError:
        pass
    
    try:
        validate_application_number("12345678901")  # Too long
        assert False, "Should have failed on too long"
    except ValueError:
        pass
    
    try:
        validate_application_number("17ABC175")  # Non-digits
        assert False, "Should have failed on non-digits"
    except ValueError:
        pass
    
    print("Application number validation tests passed")


def test_minimal_query_building():
    """Test query building for minimal tier (9 parameters only)"""
    print("Testing minimal query building...")
    
    # Test basic minimal parameters
    query, params = _build_convenience_query(
        applicant_name="Apple Inc.",
        decision_type="DENIED",
        patent_number="11788453",
        allow_balanced_params=False
    )
    
    expected_parts = [
        'firstApplicantName:"Apple Inc."',
        'patentNumber:11788453',
        'decisionTypeCodeDescriptionText:DENIED'
    ]
    
    for part in expected_parts:
        assert part in query, f"Missing query part: {part}"
    
    assert params["applicant_name"] == "Apple Inc."
    assert params["decision_type"] == "DENIED"
    assert params["patent_number"] == "11788453"
    
    print("Minimal query building tests passed")


def test_balanced_query_building():
    """Test query building for balanced tier (14 parameters)"""
    print("Testing balanced query building...")
    
    # Test balanced parameters
    query, params = _build_convenience_query(
        applicant_name="TechCorp",
        decision_type="DENIED",
        art_unit="2128",
        petition_type_code="551",
        entity_status="Small",
        allow_balanced_params=True
    )
    
    expected_parts = [
        'firstApplicantName:"TechCorp"',
        'decisionTypeCodeDescriptionText:DENIED',
        'groupArtUnitNumber:2128',
        'decisionPetitionTypeCode:551',
        'businessEntityStatusCategory:"Small"'
    ]
    
    for part in expected_parts:
        assert part in query, f"Missing query part: {part}"
    
    assert params["applicant_name"] == "TechCorp"
    assert params["art_unit"] == "2128"
    assert params["petition_type_code"] == "551"
    
    print("Balanced query building tests passed")


def test_date_range_query_building():
    """Test date range query building"""
    print("Testing date range query building...")
    
    # Test petition date range
    query, params = _build_convenience_query(
        petition_date_start="2024-01-01",
        petition_date_end="2024-12-31",
        allow_balanced_params=False
    )
    
    assert "petitionMailDate:[2024-01-01 TO 2024-12-31]" in query
    assert params["petition_date_range"] == "2024-01-01 TO 2024-12-31"
    
    # Test decision date range
    query, params = _build_convenience_query(
        decision_date_start="2024-01-01",
        allow_balanced_params=False
    )
    
    assert "decisionDate:[2024-01-01 TO *]" in query
    assert params["decision_date_range"] == "2024-01-01 TO *"
    
    print("Date range query building tests passed")


def test_progressive_disclosure_enforcement():
    """Test that minimal tier rejects balanced-only parameters"""
    print("Testing progressive disclosure enforcement...")
    
    # This should fail - balanced parameters in minimal tier
    try:
        _build_convenience_query(
            applicant_name="Apple Inc.",
            art_unit="2128",  # Balanced only
            allow_balanced_params=False
        )
        assert False, "Should have failed on balanced parameter in minimal tier"
    except ValueError as e:
        assert "art_unit" in str(e)
        assert "fpd_search_petitions_balanced" in str(e)
    
    # This should succeed - same parameters in balanced tier
    query, params = _build_convenience_query(
        applicant_name="Apple Inc.",
        art_unit="2128",
        allow_balanced_params=True
    )
    
    assert 'firstApplicantName:"Apple Inc."' in query
    assert 'groupArtUnitNumber:2128' in query
    
    print("Progressive disclosure enforcement tests passed")


def test_hybrid_query_and_parameters():
    """Test combining query string with convenience parameters"""
    print("Testing hybrid query + parameters...")
    
    query, params = _build_convenience_query(
        query="machine learning",
        applicant_name="TechCorp",
        decision_type="DENIED",
        allow_balanced_params=False
    )
    
    # Should contain both the base query and convenience parameters
    assert "(machine learning)" in query
    assert 'firstApplicantName:"TechCorp"' in query
    assert 'decisionTypeCodeDescriptionText:DENIED' in query
    assert params["base_query"] == "machine learning"
    assert params["applicant_name"] == "TechCorp"
    
    print("Hybrid query + parameters tests passed")


def test_empty_parameters():
    """Test behavior with no parameters provided"""
    print("Testing empty parameters...")
    
    # Should fail - no query or parameters
    try:
        _build_convenience_query(allow_balanced_params=False)
        assert False, "Should have failed with no parameters"
    except ValueError as e:
        assert "Must provide either" in str(e)
    
    print("Empty parameters tests passed")


def test_application_number_cleaning():
    """Test that application numbers are properly cleaned in queries"""
    print("Testing application number cleaning...")
    
    query, params = _build_convenience_query(
        application_number="17/896 175",
        allow_balanced_params=False
    )
    
    # Should be cleaned to remove spaces and slashes
    assert "applicationNumberText:17896175" in query
    assert params["application_number"] == "17896175"
    
    print("Application number cleaning tests passed")


def test_multiple_parameter_combination():
    """Test combining multiple parameters correctly"""
    print("Testing multiple parameter combination...")
    
    query, params = _build_convenience_query(
        applicant_name="Apple Inc.",
        decision_type="DENIED",
        petition_date_start="2024-01-01",
        petition_date_end="2024-12-31",
        application_number="17896175",
        allow_balanced_params=False
    )
    
    # Debug: Print the query to see what's happening
    print(f"Generated query: {query}")
    print(f"Parameters used: {params}")
    
    # Check all parts are connected with AND
    and_count = query.count(" AND ")
    # We expect 3 AND operators for 4 query parts:
    # 1. firstApplicantName:"Apple Inc."
    # 2. applicationNumberText:17896175  
    # 3. decisionTypeCodeDescriptionText:DENIED
    # 4. petitionMailDate:[2024-01-01 TO 2024-12-31]
    assert and_count == 3, f"Expected 3 AND operators, got {and_count}"
    
    # Check all parameters are represented (petition date start/end combine into one range)
    assert len(params) == 4  # 4 parameters used (date range counts as 1)
    
    print("Multiple parameter combination tests passed")


def test_special_character_handling():
    """Test handling of special characters in parameters"""
    print("Testing special character handling...")
    
    # Test quotes in company names
    query, params = _build_convenience_query(
        applicant_name="Tech Corp Inc.",
        allow_balanced_params=False
    )
    
    # Should properly quote the company name
    assert 'firstApplicantName:"Tech Corp Inc."' in query
    
    # Test deciding office with quotes
    query, params = _build_convenience_query(
        deciding_office="OFFICE OF PETITIONS",
        allow_balanced_params=False
    )
    
    assert 'finalDecidingOfficeName:"OFFICE OF PETITIONS"' in query
    
    print("Special character handling tests passed")


def run_all_tests():
    """Run all test functions"""
    print("Starting tiered convenience parameters tests...\n")
    
    try:
        test_date_validation()
        test_string_validation()
        test_application_number_validation()
        test_minimal_query_building()
        test_balanced_query_building()
        test_date_range_query_building()
        test_progressive_disclosure_enforcement()
        test_hybrid_query_and_parameters()
        test_empty_parameters()
        test_application_number_cleaning()
        test_multiple_parameter_combination()
        test_special_character_handling()
        
        print("\nAll tests passed! Tiered convenience parameters implementation is working correctly.")
        return True
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)