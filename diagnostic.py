#!/usr/bin/env python3
"""Simple diagnostic test for Copilot API issues."""

import sys
import json
from pathlib import Path

print("=== Copilot API Diagnostic ===\n")

# 1. Check token file
print("1. Checking session/token.json...")
token_file = Path("session/token.json")
if not token_file.exists():
    print("  ❌ Token file not found")
    sys.exit(1)

try:
    token_data = json.loads(token_file.read_text())
    print(f"  ✓ Token file valid JSON")
    print(f"    - Has access_token: {'access_token' in token_data}")
    print(f"    - Token age: {token_data.get('saved_at', 'N/A')}")
except json.JSONDecodeError as e:
    print(f"  ❌ Token file invalid JSON: {e}")
    sys.exit(1)

# 2. Check profile directory
print("\n2. Checking browser profile...")
profile_dir = Path("session/profile")
if profile_dir.exists():
    print(f"  ✓ Profile directory exists")
    print(f"    - Contents: {list(profile_dir.glob('*'))[:5]}")
else:
    print("  ⚠ Profile directory not found (may auto-create)")

# 3. Test basic imports
print("\n3. Testing imports...")
try:
    from copilot import CopilotClient
    print("  ✓ CopilotClient imported")
except Exception as e:
    print(f"  ❌ Failed to import: {e}")
    sys.exit(1)

# 4. Test client creation
print("\n4. Creating client...")
try:
    client = CopilotClient(mode="consumer")
    print("  ✓ Client created (consumer mode)")
except Exception as e:
    print(f"  ❌ Failed to create client: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 5. Test loading auth
print("\n5. Loading auth...")
try:
    auth = client._fresh_auth()
    if auth:
        print(f"  ✓ Auth loaded")
        print(f"    - Has cookies: {'cookies' in auth}")
        print(f"    - Has access_token: {'access_token' in auth}")
        print(f"    - Token preview: {auth.get('access_token', 'N/A')[:20]}...")
    else:
        print("  ⚠ Auth is None (anonymous mode)")
except Exception as e:
    print(f"  ❌ Failed to load auth: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 6. Test creating conversation
print("\n6. Testing conversation creation...")
try:
    from copilot.driver import Copilot
    driver = Copilot()
    print("  ✓ Driver created")
    
    # This should fail or timeout, but we're just checking if it tries
    print("  ⚠ Skipping actual API call (would be slow)")
except Exception as e:
    print(f"  ❌ Failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n=== All diagnostics passed! ===")
print("\nNext step: Try running the chat test:")
print("  python test.py")
