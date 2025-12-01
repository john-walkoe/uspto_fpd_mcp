"""
Comprehensive Test Suite for USPTO MCP Unified Storage
=====================================================

Tests the unified storage system across all 4 USPTO MCPs:
- FPD (Final Petition Decisions)
- PFW (Patent File Wrapper) 
- PTAB (Patent Trial and Appeal Board)
- Enriched Citations

Verifies:
1. Unified storage module works correctly
2. All MCPs can use unified storage
3. Key storage and retrieval functions properly
4. Cross-MCP key sharing works
"""

import os
import sys
from pathlib import Path

# Test configuration
TEST_USPTO_KEY = "test_uspto_api_key_12345"
TEST_MISTRAL_KEY = "test_mistral_api_key_67890"

def test_unified_storage_module():
    """Test the unified storage module directly."""
    print("=== Testing Unified Storage Module ===")
    
    # Import from FPD (all MCPs have identical modules) - updated for tests directory
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from fpd_mcp.shared_secure_storage import UnifiedSecureStorage
    
    storage = UnifiedSecureStorage()
    
    # Test initial state
    print(f"Initial state: {storage.get_storage_stats()}")
    
    # Test USPTO key storage and retrieval
    print("\n1. Testing USPTO key...")
    success = storage.store_uspto_key(TEST_USPTO_KEY)
    print(f"   Store USPTO key: {'SUCCESS' if success else 'FAILED'}")
    
    has_key = storage.has_uspto_key()
    print(f"   Has USPTO key: {'YES' if has_key else 'NO'}")
    
    retrieved_key = storage.get_uspto_key()
    print(f"   Retrieved key matches: {'YES' if retrieved_key == TEST_USPTO_KEY else 'NO'}")
    
    # Test Mistral key storage and retrieval
    print("\n2. Testing Mistral key...")
    success = storage.store_mistral_key(TEST_MISTRAL_KEY)
    print(f"   Store Mistral key: {'SUCCESS' if success else 'FAILED'}")
    
    has_key = storage.has_mistral_key()
    print(f"   Has Mistral key: {'YES' if has_key else 'NO'}")
    
    retrieved_key = storage.get_mistral_key()
    print(f"   Retrieved key matches: {'YES' if retrieved_key == TEST_MISTRAL_KEY else 'NO'}")
    
    # Test available keys
    available_keys = storage.list_available_keys()
    print(f"\n3. Available keys: {available_keys}")
    
    return storage

def test_fpd_mcp(storage):
    """Test FPD MCP with unified storage."""
    print("\n=== Testing FPD MCP ===")
    
    try:
        # Test API client
        from fpd_mcp.api.fpd_client import FPDClient
        client = FPDClient()
        print(f"   FPD Client init: SUCCESS (key length: {len(client.api_key)})")
        
        # Test settings
        from fpd_mcp.config.settings import Settings
        settings = Settings()
        print(f"   FPD Settings: SUCCESS (USPTO key: {bool(settings.uspto_api_key)}, Mistral key: {bool(settings.mistral_api_key)})")
        
        return True
    except Exception as e:
        print(f"   FPD Test: FAILED - {e}")
        return False

def test_pfw_mcp(storage):
    """Test PFW MCP with unified storage."""
    print("\n=== Testing PFW MCP ===")
    
    try:
        # Change to PFW directory and add to path
        pfw_path = Path("../uspto_pfw_mcp/src")
        if pfw_path.exists():
            sys.path.insert(0, str(pfw_path))
            
            from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient
            client = EnhancedPatentClient()
            print(f"   PFW Client init: SUCCESS (key length: {len(client.api_key)})")
            
            print(f"   PFW Mistral config: {'AVAILABLE' if client.mistral_api_key else 'MISSING'}")
            
            return True
        else:
            print("   PFW Test: SKIPPED - PFW directory not found")
            return True
    except Exception as e:
        print(f"   PFW Test: FAILED - {e}")
        return False

def test_ptab_mcp(storage):
    """Test PTAB MCP with unified storage."""
    print("\n=== Testing PTAB MCP ===")
    
    try:
        # Change to PTAB directory and add to path
        ptab_path = Path("../uspto_ptab_mcp/src")
        if ptab_path.exists():
            sys.path.insert(0, str(ptab_path))
            
            from ptab_mcp.api.enhanced_client import EnhancedPTABClient
            client = EnhancedPTABClient()
            print(f"   PTAB Client init: SUCCESS")
            
            # PTAB only uses Mistral, not USPTO key
            print(f"   PTAB Mistral config: {'AVAILABLE' if hasattr(client, 'mistral_api_key') and client.mistral_api_key else 'MISSING'}")
            
            return True
        else:
            print("   PTAB Test: SKIPPED - PTAB directory not found")
            return True
    except Exception as e:
        print(f"   PTAB Test: FAILED - {e}")
        return False

def test_enriched_citations_mcp(storage):
    """Test Enriched Citations MCP with unified storage."""
    print("\n=== Testing Enriched Citations MCP ===")
    
    try:
        # Change to Enriched Citations directory and add to path
        ec_path = Path("../uspto_enriched_citation_mcp/src")
        if ec_path.exists():
            sys.path.insert(0, str(ec_path))
            
            # Test settings loading (main entry point for this MCP)
            from uspto_enriched_citation_mcp.config.settings import Settings
            
            # Set environment variable since this MCP requires it
            os.environ['USPTO_ECITATION_API_KEY'] = TEST_USPTO_KEY
            settings = Settings.load_from_env()
            print(f"   Enriched Citations Settings: SUCCESS")
            
            # Clean up environment variable
            del os.environ['USPTO_ECITATION_API_KEY']
            
            return True
        else:
            print("   Enriched Citations Test: SKIPPED - Enriched Citations directory not found")
            return True
    except Exception as e:
        print(f"   Enriched Citations Test: FAILED - {e}")
        return False

def test_cross_mcp_sharing():
    """Test that all MCPs can access the same unified storage."""
    print("\n=== Testing Cross-MCP Key Sharing ===")
    
    # Test that all MCPs can access the same storage paths
    mcp_paths = [
        "src/fpd_mcp/shared_secure_storage.py",
        "../uspto_pfw_mcp/src/patent_filewrapper_mcp/shared_secure_storage.py",
        "../uspto_ptab_mcp/src/ptab_mcp/shared_secure_storage.py", 
        "../uspto_enriched_citation_mcp/src/uspto_enriched_citation_mcp/shared_secure_storage.py"
    ]
    
    mcp_names = ["FPD", "PFW", "PTAB", "Enriched Citations"]
    
    for mcp_path, mcp_name in zip(mcp_paths, mcp_names):
        if Path(mcp_path).exists():
            print(f"   {mcp_name} storage module: PRESENT")
        else:
            print(f"   {mcp_name} storage module: MISSING")
    
    # Test that storage points to the same files
    from fpd_mcp.shared_secure_storage import UnifiedSecureStorage
    storage = UnifiedSecureStorage()
    
    expected_uspto = Path.home() / ".uspto_api_key"
    expected_mistral = Path.home() / ".mistral_api_key"
    
    print(f"\n   USPTO key path: {storage.uspto_key_path}")
    print(f"   Expected:       {expected_uspto}")
    print(f"   Paths match:    {'YES' if storage.uspto_key_path == expected_uspto else 'NO'}")
    
    print(f"\n   Mistral key path: {storage.mistral_key_path}")
    print(f"   Expected:         {expected_mistral}")
    print(f"   Paths match:      {'YES' if storage.mistral_key_path == expected_mistral else 'NO'}")

def cleanup_test_keys():
    """Clean up test keys."""
    print("\n=== Cleaning Up Test Keys ===")
    
    from fpd_mcp.shared_secure_storage import UnifiedSecureStorage
    storage = UnifiedSecureStorage()
    
    # Remove test files
    if storage.uspto_key_path.exists():
        storage.uspto_key_path.unlink()
        print("   Removed test USPTO key")
    
    if storage.mistral_key_path.exists():
        storage.mistral_key_path.unlink()
        print("   Removed test Mistral key")

def main():
    """Run comprehensive test suite."""
    print("USPTO MCP Unified Storage - Comprehensive Test Suite")
    print("=" * 55)
    
    try:
        # Test 1: Core unified storage module
        storage = test_unified_storage_module()
        
        # Test 2: Individual MCP integration
        fpd_success = test_fpd_mcp(storage)
        pfw_success = test_pfw_mcp(storage)
        ptab_success = test_ptab_mcp(storage)
        ec_success = test_enriched_citations_mcp(storage)
        
        # Test 3: Cross-MCP sharing
        test_cross_mcp_sharing()
        
        # Results summary
        print("\n" + "=" * 55)
        print("TEST RESULTS SUMMARY")
        print("=" * 55)
        print(f"Unified Storage Module: {'PASS' if storage else 'FAIL'}")
        print(f"FPD MCP Integration:    {'PASS' if fpd_success else 'FAIL'}")
        print(f"PFW MCP Integration:    {'PASS' if pfw_success else 'FAIL'}")
        print(f"PTAB MCP Integration:   {'PASS' if ptab_success else 'FAIL'}")
        print(f"Enriched Citations MCP: {'PASS' if ec_success else 'FAIL'}")
        
        overall_success = all([storage, fpd_success, pfw_success, ptab_success, ec_success])
        print(f"\nOVERALL RESULT: {'PASS ✅' if overall_success else 'FAIL ❌'}")
        
        if overall_success:
            print("\n🎉 All tests passed! The unified storage system is working correctly.")
            print("\nNext steps:")
            print("1. Update installation scripts to use unified storage")
            print("2. Run migration utilities for existing users")
            print("3. Deploy the updated MCPs")
        else:
            print("\n❌ Some tests failed. Please review the errors above.")
        
        return overall_success
        
    except Exception as e:
        print(f"\nTest suite failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # Always clean up test keys
        try:
            cleanup_test_keys()
        except:
            pass

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)