#!/usr/bin/env python3
"""
Script to run all tests in the tests directory
"""

import subprocess
import sys
from pathlib import Path

def run_test(test_file):
    """Run a single test file and return the result"""
    print(f"\n{'='*60}")
    print(f"RUNNING: {test_file}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run([
            sys.executable, 
            str(Path("tests") / test_file)
        ], capture_output=False, text=True, cwd=Path(__file__).parent)
        
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Error running {test_file}: {e}")
        return False

def main():
    """Run all tests"""
    test_files = [
        "test_building_type_geometry.py",
        "test_mcp_server.py", 
        "test_construction_set_creation.py",
        "test_construction_creation.py",
        "test_apply_construction_set.py"
    ]
    
    print("🚀 Running All OpenStudio Standards Database Tests")
    print("="*60)
    
    results = {}
    
    for test_file in test_files:
        success = run_test(test_file)
        results[test_file] = success
    
    # Summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")
    
    passed = 0
    total = len(test_files)
    
    for test_file, success in results.items():
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{test_file:<35} {status}")
        if success:
            passed += 1
    
    print(f"{'-'*60}")
    print(f"Overall: {passed}/{total} test files passed")
    
    if passed == total:
        print("🎉 All tests passed!")
        return 0
    else:
        print("⚠️  Some tests failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
