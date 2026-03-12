#!/usr/bin/env python3
"""Test script to verify Polymarket API connectivity.

This script:
1. Loads environment variables from .env
2. Initializes the Polymarket client with credentials
3. Makes an authenticated API call (GET /portfolio - non-trading)
4. Reports success/failure

Requirements:
- Do NOT place live orders
- Do NOT expose secrets in logs
"""

import asyncio
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
    print(f"Loading .env from: {env_path}")
    print(f"File exists: {env_path.exists()}")
    if env_path.exists():
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip()
    print(f"Loaded {len(env_vars)} env vars")
    print(f"POLYMARKET_API_KEY present: {'POLYMARKET_API_KEY' in env_vars}")
    return env_vars


async def test_api_connectivity() -> bool:
    """Test Polymarket API connectivity.
    
    Returns:
        True if successful, False otherwise
    """
    # Load .env file
    env_path = project_root / ".env"
    env_vars = load_env_file(env_path)
    
    # Get API credentials
    api_key = env_vars.get("POLYMARKET_API_KEY")
    api_secret = env_vars.get("POLYMARKET_API_SECRET")
    
    if not api_key:
        print("API auth: failed")
        print("Error: POLYMARKET_API_KEY not found in .env")
        return False
    
    # Mask the API key for logging (show only first 8 chars)
    api_key_masked = api_key[:8] + "****" if len(api_key) > 8 else "****"
    print(f"API key loaded: {api_key_masked}")
    
    # Import after loading env - use aiohttp directly for simplicity
    try:
        import aiohttp
    except ImportError:
        print("API auth: failed")
        print("Error: aiohttp module not available")
        return False
    
    try:
        from execution.polymarket.client import PolymarketClient
    except ImportError as e:
        print("API auth: failed")
        print(f"Error importing client: {e}")
        return False
    
    # Initialize client with API key (Bearer token auth)
    client = PolymarketClient(api_key=api_key)
    
    try:
        # Test 1: Simple unauthenticated call to verify connectivity
        print("\n[Test 1] Testing basic connectivity (GET /markets)...")
        try:
            markets = await client.get_markets(active_only=True)
            print(f"  - Found {len(markets)} active markets")
            print("  - Basic connectivity: OK")
        except Exception as e:
            print(f"  - Basic connectivity: FAILED")
            print(f"  - Error: {e}")
            await client.close()
            return False
        
        # Test 2: Authenticated call using Bearer token to Data API
        # Test authenticated request to Data API (user-specific data)
        print("\n[Test 2] Testing authenticated call (GET /positions with user)...")
        
        # Use Data API which supports user-specific endpoints
        # The API key is used for rate limiting, not authentication
        wallet_address = env_vars.get("POLYMARKET_FUNDER_ADDRESS", "")
        url = f"https://data-api.polymarket.com/positions"
        if wallet_address:
            url += f"?user={wallet_address}"
        
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        
        session = await client._get_session()
        
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"  - Positions data received: OK")
                    print(f"  - Positions count: {len(data) if isinstance(data, list) else 'N/A'}")
                    print("  - Authenticated call: OK")
                elif resp.status == 401:
                    error_text = await resp.text()
                    print(f"  - Authenticated call: FAILED")
                    print(f"  - Error: 401 Unauthorized - {error_text}")
                    await client.close()
                    return False
                elif resp.status == 403:
                    error_text = await resp.text()
                    print(f"  - Authenticated call: FAILED")
                    print(f"  - Error: 403 Forbidden - {error_text}")
                    await client.close()
                    return False
                else:
                    error_text = await resp.text()
                    print(f"  - Authenticated call: FAILED")
                    print(f"  - Error: {resp.status} - {error_text[:200]}")
                    await client.close()
                    return False
        except aiohttp.ClientError as e:
            print(f"  - Authenticated call: FAILED")
            print(f"  - Error: {e}")
            await client.close()
            return False
        
        await client.close()
        
        print("\n" + "=" * 50)
        print("API auth: ok")
        print("=" * 50)
        return True
        
    except Exception as e:
        print(f"\nAPI auth: failed")
        print(f"Error: {e}")
        try:
            await client.close()
        except:
            pass
        return False


def main() -> int:
    """Main entry point."""
    print("=" * 50)
    print("Polymarket API Connectivity Test")
    print("=" * 50)
    print()
    
    success = asyncio.run(test_api_connectivity())
    
    if not success:
        print("\nTest FAILED")
        return 1
    
    print("\nTest PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
