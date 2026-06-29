#!/usr/bin/env python3
"""
Account2 API Key Derivation Script

Derives a Polymarket CLOB API key for Account2 (Magic-wallet) using signature_type=1 (POLY_PROXY).
The API credentials are saved to account2.env.
"""

import os
import sys
from pathlib import Path

# Add venv to path for standalone execution
venv_site = "/opt/executor/app/venv/lib/python3.10/site-packages"
if venv_site not in sys.path:
    sys.path.insert(0, venv_site)

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


def save_creds_to_env(env_path: Path, creds: ApiCreds) -> None:
    """Append API credentials to the env file."""
    with open(env_path, "a") as f:
        f.write(f"\nAPI_KEY={creds.api_key}\n")
        f.write(f"API_SECRET={creds.api_secret}\n")
        f.write(f"API_PASSPHRASE={creds.api_passphrase}\n")


def main():
    print("=" * 60)
    print("Account2 API Key Derivation (POLY_PROXY)")
    print("=" * 60)
    
    # Load private key from env file
    env_vars = load_env_file(ENV_FILE)
    
    private_key = env_vars.get("PRIVATE_KEY")
    if not private_key:
        print("ERROR: PRIVATE_KEY not found in account2.env")
        sys.exit(1)
    
    print(f"\nLoaded environment from: {ENV_FILE}")
    print(f"Signer's address: {SIGNER_ADDRESS}")
    print(f"Funder (proxy) address: {FUNDER_ADDRESS}")
    print(f"Signature type: {SIGNATURE_TYPE} (POLY_PROXY)")
    print(f"Chain ID: {CHAIN_ID}")
    print(f"Host: {HOST}")
    
    # Initialize ClobClient
    print("\nInitializing ClobClient...")
    try:
        client = ClobClient(
            host=HOST,
            chain_id=CHAIN_ID,
            key=private_key,
            signature_type=SIGNATURE_TYPE,
            funder=FUNDER_ADDRESS,
        )
        print("ClobClient initialized successfully")
    except Exception as e:
        print(f"ERROR initializing ClobClient: {e}")
        sys.exit(1)
    
    # Derive API key
    print("\nCalling create_or_derive_api_key()...")
    try:
        creds = client.create_or_derive_api_key()
        print("\nSUCCESS: API key derived successfully!")
        print(f"API_KEY (UUID): {creds.api_key}")
        print(f"API_SECRET: [REDACTED - saved to env file]")
        print(f"API_PASSPHRASE: [REDACTED - saved to env file]")
        
        # Save credentials to env file
        save_creds_to_env(ENV_FILE, creds)
        print(f"\nCredentials saved to: {ENV_FILE}")
        
    except Exception as e:
        print(f"\nERROR from Polymarket API: {e}")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("Setup complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
