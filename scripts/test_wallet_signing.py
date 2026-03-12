#!/usr/bin/env python3
"""Test script to verify wallet signing/auth path.

This script:
1. Loads POLYMARKET_PRIVATE_KEY from .env
2. Uses eth_account to verify the private key is valid
3. Verifies that an address can be derived from the private key
4. Tests a minimal signing operation (sign a test message)

Requirements:
- Do NOT place live orders
- Do NOT expose the full private key in logs
- Report success/failure with exact error if failed
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


def load_env_file(env_path: Path) -> dict:
    """Load environment variables from .env file.
    
    Args:
        env_path: Path to .env file
        
    Returns:
        Dict of environment variables
    """
    env_vars = {}
    if env_path.exists():
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip()
    return env_vars


def test_wallet_signing() -> bool:
    """Test wallet signing functionality.
    
    Returns:
        True if successful, False otherwise
    """
    # Load .env file
    env_path = project_root / ".env"
    env_vars = load_env_file(env_path)
    
    # Get private key - check POLYMARKET_PRIVATE_KEY first (as specified by user)
    private_key = env_vars.get("POLYMARKET_PRIVATE_KEY")
    
    if not private_key:
        # Fallback to other common names
        private_key = env_vars.get("METAMASK_PRIVATE_KEY")
        key_name = "METAMASK_PRIVATE_KEY"
    else:
        key_name = "POLYMARKET_PRIVATE_KEY"
    
    if not private_key:
        print("Wallet signing: failed")
        print(f"Error: Neither POLYMARKET_PRIVATE_KEY nor METAMASK_PRIVATE_KEY found in .env")
        return False
    
    # Mask the private key for logging (show only first 6 and last 4 chars)
    key_len = len(private_key)
    if key_len > 10:
        key_masked = f"{private_key[:6]}...{private_key[-4:]} (len={key_len})"
    else:
        key_masked = "****"
    print(f"Private key loaded: {key_masked}")
    
    # Try to import eth_account
    try:
        from eth_account import Account
    except ImportError as e:
        print("Wallet signing: failed")
        print(f"Error: eth_account module not available: {e}")
        return False
    
    # Try to decode and verify the private key
    try:
        # Handle both formats: with '0x' prefix and without
        if not private_key.startswith('0x'):
            private_key = '0x' + private_key
        
        # Test if the private key is valid by creating an account
        # This will raise an exception if the key is invalid
        account = Account.from_key(private_key)
        
        # Get the derived address
        address = account.address
        address_masked = f"{address[:6]}...{address[-4:]}"
        print(f"Derived address: {address_masked}")
        
    except Exception as e:
        print("Wallet signing: failed")
        print(f"Error: Failed to derive address from private key: {e}")
        return False
    
    # Test minimal signing operation
    try:
        # Sign a test message (non-transaction, minimal operation)
        # Use the encode_defunct approach for compatibility
        from eth_account.messages import encode_defunct
        
        test_message = "Polymarket Bot Test Message"
        message = encode_defunct(text=test_message)
        signed_message = account.sign_message(message)
        
        # Verify the signature
        recovered_address = Account.recover_message(message, signature=signed_message.signature)
        
        if recovered_address.lower() == address.lower():
            print(f"Signing test: OK")
            print(f"Signature verified successfully")
        else:
            print("Wallet signing: failed")
            print(f"Error: Signature verification failed - recovered address doesn't match")
            return False
            
    except Exception as e:
        print("Wallet signing: failed")
        print(f"Error: Signing operation failed: {e}")
        return False
    
    print("\n" + "=" * 50)
    print("Wallet signing: ok")
    print("=" * 50)
    return True


def main() -> int:
    """Main entry point."""
    print("=" * 50)
    print("Wallet Signing Verification Test")
    print("=" * 50)
    print()
    
    success = test_wallet_signing()
    
    if not success:
        print("\nTest FAILED")
        return 1
    
    print("\nTest PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
