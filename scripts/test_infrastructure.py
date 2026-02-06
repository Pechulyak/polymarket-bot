#!/usr/bin/env python3
"""
Infrastructure Test Script for Polymarket Trading Bot
Tests PostgreSQL and Redis connectivity and basic operations.

Usage:
    python scripts/test_infrastructure.py

Requirements:
    pip install psycopg2-binary redis python-dotenv
"""

import os
import sys
import time
from datetime import datetime
from typing import Tuple, Optional

# Try to import required packages
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("❌ psycopg2-binary not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

try:
    import redis
except ImportError:
    print("❌ redis not installed. Run: pip install redis")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("⚠️  python-dotenv not installed. Run: pip install python-dotenv")


class InfrastructureTester:
    """Test infrastructure components."""
    
    def __init__(self):
        self.postgres_connected = False
        self.redis_connected = False
        self.results = []
        
    def log(self, message: str, status: str = "info"):
        """Log test results."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        icon = {"info": "ℹ️", "success": "✅", "error": "❌", "warning": "⚠️"}.get(status, "ℹ️")
        print(f"{icon} [{timestamp}] {message}")
        self.results.append({"time": timestamp, "message": message, "status": status})
    
    def test_postgres_connection(self) -> bool:
        """Test PostgreSQL connection."""
        self.log("Testing PostgreSQL connection...", "info")
        
        # Get connection parameters
        db_url = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/polymarket")
        
        try:
            # Parse connection string
            if db_url.startswith("postgresql://"):
                # Extract connection info from URL
                conn_parts = db_url.replace("postgresql://", "").split("@")
                if len(conn_parts) == 2:
                    credentials, host_db = conn_parts
                    user_pass = credentials.split(":")
                    host_port_db = host_db.split("/")
                    
                    user = user_pass[0]
                    password = user_pass[1] if len(user_pass) > 1 else ""
                    host_port = host_port_db[0].split(":")
                    host = host_port[0]
                    port = int(host_port[1]) if len(host_port) > 1 else 5432
                    database = host_port_db[1] if len(host_port_db) > 1 else "polymarket"
                else:
                    raise ValueError("Invalid DATABASE_URL format")
            else:
                user = os.getenv("POSTGRES_USER", "postgres")
                password = os.getenv("POSTGRES_PASSWORD", "password")
                host = os.getenv("POSTGRES_HOST", "localhost")
                port = int(os.getenv("POSTGRES_PORT", "5432"))
                database = os.getenv("POSTGRES_DB", "polymarket")
            
            # Try to connect
            conn = psycopg2.connect(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
                connect_timeout=5
            )
            
            # Test connection
            cursor = conn.cursor()
            cursor.execute("SELECT version();")
            version = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            
            self.log(f"PostgreSQL connected: {version}", "success")
            self.postgres_connected = True
            return True
            
        except psycopg2.OperationalError as e:
            self.log(f"PostgreSQL connection failed: {e}", "error")
            return False
        except Exception as e:
            self.log(f"PostgreSQL error: {e}", "error")
            return False
    
    def test_postgres_tables(self) -> bool:
        """Test PostgreSQL tables exist."""
        if not self.postgres_connected:
            self.log("Skipping PostgreSQL table check (no connection)", "warning")
            return False
        
        self.log("Checking PostgreSQL tables...", "info")
        
        expected_tables = [
            "market_data",
            "opportunities", 
            "trades",
            "positions",
            "bankroll",
            "risk_events",
            "fee_schedule",
            "api_health"
        ]
        
        try:
            db_url = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/polymarket")
            
            # Parse connection string (simplified)
            if db_url.startswith("postgresql://"):
                conn_parts = db_url.replace("postgresql://", "").split("@")
                credentials, host_db = conn_parts
                user_pass = credentials.split(":")
                host_port_db = host_db.split("/")
                
                user = user_pass[0]
                password = user_pass[1] if len(user_pass) > 1 else ""
                host_port = host_port_db[0].split(":")
                host = host_port[0]
                port = int(host_port[1]) if len(host_port) > 1 else 5432
                database = host_port_db[1] if len(host_port_db) > 1 else "polymarket"
            else:
                user = os.getenv("POSTGRES_USER", "postgres")
                password = os.getenv("POSTGRES_PASSWORD", "password")
                host = os.getenv("POSTGRES_HOST", "localhost")
                port = int(os.getenv("POSTGRES_PORT", "5432"))
                database = os.getenv("POSTGRES_DB", "polymarket")
            
            conn = psycopg2.connect(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password
            )
            cursor = conn.cursor()
            
            # Check tables
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
            """)
            existing_tables = [row[0] for row in cursor.fetchall()]
            
            missing_tables = [t for t in expected_tables if t not in existing_tables]
            
            if missing_tables:
                self.log(f"Missing tables: {', '.join(missing_tables)}", "error")
                result = False
            else:
                self.log(f"All {len(expected_tables)} tables found", "success")
                result = True
            
            # Check bankroll record
            cursor.execute("SELECT COUNT(*) FROM bankroll;")
            bankroll_count = cursor.fetchone()[0]
            self.log(f"Bankroll records: {bankroll_count}", "success" if bankroll_count > 0 else "warning")
            
            cursor.close()
            conn.close()
            
            return result
            
        except Exception as e:
            self.log(f"PostgreSQL table check failed: {e}", "error")
            return False
    
    def test_redis_connection(self) -> bool:
        """Test Redis connection."""
        self.log("Testing Redis connection...", "info")
        
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        
        try:
            if redis_url.startswith("redis://"):
                # Parse Redis URL
                conn_str = redis_url.replace("redis://", "")
                if "/" in conn_str:
                    host_port, db = conn_str.rsplit("/", 1)
                    db = int(db)
                else:
                    host_port = conn_str
                    db = 0
                
                if ":" in host_port:
                    host, port = host_port.split(":")
                    port = int(port)
                else:
                    host = host_port
                    port = 6379
            else:
                host = os.getenv("REDIS_HOST", "localhost")
                port = int(os.getenv("REDIS_PORT", "6379"))
                db = int(os.getenv("REDIS_DB", "0"))
            
            # Connect to Redis
            client = redis.Redis(
                host=host,
                port=port,
                db=db,
                socket_connect_timeout=5,
                decode_responses=True
            )
            
            # Test connection
            if client.ping():
                info = client.info()
                version = info.get("redis_version", "unknown")
                self.log(f"Redis connected: v{version}", "success")
                self.redis_connected = True
                return True
            else:
                self.log("Redis ping failed", "error")
                return False
                
        except redis.ConnectionError as e:
            self.log(f"Redis connection failed: {e}", "error")
            return False
        except Exception as e:
            self.log(f"Redis error: {e}", "error")
            return False
    
    def test_redis_operations(self) -> bool:
        """Test Redis basic operations."""
        if not self.redis_connected:
            self.log("Skipping Redis operations test (no connection)", "warning")
            return False
        
        self.log("Testing Redis operations...", "info")
        
        try:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            
            if redis_url.startswith("redis://"):
                conn_str = redis_url.replace("redis://", "")
                if "/" in conn_str:
                    host_port, db = conn_str.rsplit("/", 1)
                    db = int(db)
                else:
                    host_port = conn_str
                    db = 0
                
                if ":" in host_port:
                    host, port = host_port.split(":")
                    port = int(port)
                else:
                    host = host_port
                    port = 6379
            else:
                host = os.getenv("REDIS_HOST", "localhost")
                port = int(os.getenv("REDIS_PORT", "6379"))
                db = int(os.getenv("REDIS_DB", "0"))
            
            client = redis.Redis(
                host=host,
                port=port,
                db=db,
                decode_responses=True
            )
            
            # Test SET
            test_key = "infrastructure_test"
            test_value = f"test_{datetime.now().isoformat()}"
            client.set(test_key, test_value, ex=60)  # 60 second expiry
            
            # Test GET
            retrieved = client.get(test_key)
            if retrieved == test_value:
                self.log("Redis SET/GET operations working", "success")
            else:
                self.log("Redis GET returned unexpected value", "error")
                return False
            
            # Test DELETE
            client.delete(test_key)
            if client.get(test_key) is None:
                self.log("Redis DELETE operation working", "success")
            else:
                self.log("Redis DELETE failed", "error")
                return False
            
            # Test persistence info
            info = client.info("persistence")
            aof_enabled = info.get("aof_enabled", 0)
            if aof_enabled:
                self.log("Redis AOF persistence enabled", "success")
            else:
                self.log("Redis AOF persistence disabled", "warning")
            
            return True
            
        except Exception as e:
            self.log(f"Redis operations test failed: {e}", "error")
            return False
    
    def run_all_tests(self) -> Tuple[bool, dict]:
        """Run all infrastructure tests."""
        print("\n" + "="*60)
        print("🔧 INFRASTRUCTURE TEST SUITE")
        print("="*60 + "\n")
        
        start_time = time.time()
        
        # PostgreSQL tests
        self.log("📊 POSTGRESQL TESTS", "info")
        pg_conn = self.test_postgres_connection()
        pg_tables = self.test_postgres_tables() if pg_conn else False
        
        print()
        
        # Redis tests
        self.log("🚀 REDIS TESTS", "info")
        redis_conn = self.test_redis_connection()
        redis_ops = self.test_redis_operations() if redis_conn else False
        
        elapsed = time.time() - start_time
        
        # Summary
        print("\n" + "="*60)
        print("📋 TEST SUMMARY")
        print("="*60)
        
        all_passed = pg_conn and redis_conn
        
        status_icon = "✅" if all_passed else "❌"
        status_text = "PASSED" if all_passed else "FAILED"
        
        print(f"\n{status_icon} Overall Status: {status_text}")
        print(f"⏱️  Execution Time: {elapsed:.2f}s")
        print()
        print("PostgreSQL:")
        print(f"  Connection: {'✅' if pg_conn else '❌'}")
        print(f"  Tables: {'✅' if pg_tables else '❌'}")
        print()
        print("Redis:")
        print(f"  Connection: {'✅' if redis_conn else '❌'}")
        print(f"  Operations: {'✅' if redis_ops else '❌'}")
        print()
        
        if all_passed:
            print("🎉 All infrastructure tests passed!")
            print("   Your local development environment is ready.")
        else:
            print("⚠️  Some tests failed.")
            print("   Make sure Docker containers are running:")
            print("   docker-compose up -d postgres redis")
        
        print("\n" + "="*60 + "\n")
        
        return all_passed, {
            "postgres": {"connection": pg_conn, "tables": pg_tables},
            "redis": {"connection": redis_conn, "operations": redis_ops},
            "elapsed_seconds": elapsed
        }


def main():
    """Main entry point."""
    tester = InfrastructureTester()
    success, results = tester.run_all_tests()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
