#!/usr/bin/env python3
"""
Account2 Diagnostic Script

Captures raw exception data and headers from create_or_derive_api_key() flow.
READ-ONLY - no fixes, no commits.
"""

import os
import sys
from pathlib import Path

# Add venv to path for standalone execution
venv_site = "/opt/executor/app/venv/lib/python3.10/site-packages"
if venv_site not in sys.path:
    sys.path.insert(0, venv_site)

import httpx
from py_clob_client_v2 import ClobClient
from py_clob_client_v2.clob_types import ApiCreds

# Constants
HOST = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon
SIGNATURE_TYPE = 1  # POLY_PROXY

# Known addresses
FUNDER_ADDRESS = "0x302F067006A958604365c94d73d7632081294a10"
SIGNER_ADDRESS = "0xdDb1Ac6215857437dD6d5b629f4dF6b4c572E368"

# Paths
ACCOUNT_DIR = Path("/opt/executor/app/accounts")
ENV_FILE = ACCOUNT_DIR / "account2.env"


def load_env_file(env_path: Path) -> dict:
    """Load environment variables from .env file."""
    env_vars = {}
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env_vars[key.strip()] = value.strip()
    return env_vars


def main():
    print("=" * 70)
    print("Account2 Diagnostic - Raw Exception and Header Capture")
    print("=" * 70)
    
    # Load private key from env file
    env_vars = load_env_file(ENV_FILE)
    
    private_key = env_vars.get("PRIVATE_KEY")
    if not private_key:
        print("ERROR: PRIVATE_KEY not found in account2.env")
        sys.exit(1)
    
    print(f"\nSigner's address: {SIGNER_ADDRESS}")
    print(f"Funder (proxy) address: {FUNDER_ADDRESS}")
    print(f"Signature type: {SIGNATURE_TYPE} (POLY_PROXY)")
    
    # Initialize ClobClient
    print("\nInitializing ClobClient...")
    client = ClobClient(
        host=HOST,
        chain_id=CHAIN_ID,
        key=private_key,
        signature_type=SIGNATURE_TYPE,
        funder=FUNDER_ADDRESS,
    )
    print("ClobClient initialized")
    
    # Capture create_api_key exception
    print("\n" + "-" * 70)
    print("CAPTURING create_api_key() EXCEPTION")
    print("-" * 70)
    
    try:
        creds_create = client.create_api_key()
        print(f"create_api_key succeeded unexpectedly: {creds_create.api_key}")
    except Exception as e:
        print(f"\nException type: {type(e).__name__}")
        print(f"Exception string repr: {repr(e)}")
        print(f"Exception str(): {str(e)}")
        
        # Try to extract response details if available
        if hasattr(e, 'response'):
            resp = e.response
            print(f"\n--- HTTP Response Details ---")
            print(f"Status code: {resp.status_code}")
            print(f"Headers: {dict(resp.headers)}")
            print(f"Body text: {resp.text}")
            try:
                print(f"Body JSON: {resp.json()}")
            except:
                pass
        elif hasattr(e, 'args') and len(e.args) > 0:
            print(f"\n--- Exception args ---")
            for i, arg in enumerate(e.args):
                print(f"  arg[{i}]: {repr(arg)}")
                if isinstance(arg, dict):
                    for k, v in arg.items():
                        print(f"    {k}: {repr(v)}")
    
    # Capture derive_api_key result and headers
    print("\n" + "-" * 70)
    print("CAPTURING derive_api_key() RESULT AND HEADERS")
    print("-" * 70)
    
    # Hook into the client's _l1_headers method
    original_l1_headers = client._l1_headers
    
    captured_headers = {}
    
    def capture_l1_headers(nonce=None):
        headers = original_l1_headers(nonce=nonce)
        captured_headers['l1_headers'] = dict(headers)
        print(f"\n--- Captured L1 Headers ---")
        for key, value in headers.items():
            # Truncate signature value for display
            if 'signature' in key.lower():
                display_value = value[:40] + "..." + value[-20:] if len(value) > 60 else value
                print(f"  {key}: {display_value}")
            else:
                print(f"  {key}: {value}")
        return headers
    
    client._l1_headers = capture_l1_headers
    
    try:
        creds_derive = client.derive_api_key()
        print(f"\nderive_api_key result:")
        print(f"  api_key: {creds_derive.api_key}")
        print(f"  api_secret: {creds_derive.api_secret}")
        print(f"  api_passphrase: {creds_derive.api_passphrase}")
        
        # Check if matches saved
        saved_api_key = env_vars.get("API_KEY", "NOT FOUND")
        print(f"\n--- Comparison ---")
        print(f"Saved API_KEY in account2.env: {saved_api_key}")
        print(f"Newly derived api_key: {creds_derive.api_key}")
        print(f"Match: {saved_api_key == creds_derive.api_key}")
        
    except Exception as e:
        print(f"\nderive_api_key() exception: {repr(e)}")
        if hasattr(e, 'response'):
            resp = e.response
            print(f"Status: {resp.status_code}, Body: {resp.text}")
    
    print("\n" + "=" * 70)
    print("Diagnostic complete (READ-ONLY)")
    print("=" * 70)


if __name__ == "__main__":
    main()
