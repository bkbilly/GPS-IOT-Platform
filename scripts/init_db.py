"""
Database Initialization Script
Run this to set up the database schema
"""
import asyncio
import sys
from database import init_database
from config import get_settings
from schemas import UserCreate


async def main():
    """Initialize database schema"""
    settings = get_settings()
    
    print("=== GPS/IoT Platform Database Initialization ===\n")
    print(f"Database URL: {settings.database_url.replace('password', '***')}\n")
    
    try:
        print("Creating database schema...")
        db_service = await init_database(settings.database_url)
        
        print("✓ Database schema created successfully!")
        
        # Create default user
        print("\nChecking for default user...")
        try:
            existing_user = await db_service.get_user(1)
            if not existing_user:
                print("Creating default admin user (ID: 1)...")
                default_user = UserCreate(
                    username="admin",
                    email="admin@example.com",
                    password="admin_password",  # Must be > 8 chars
                    notification_channels={}
                )
                user = await db_service.create_user(default_user)
                print(f"✓ Default user created: {user.username} (ID: {user.id})")
                print("  Email: admin@example.com")
                print("  Password: admin_password")
            else:
                print(f"ℹ Default user already exists (ID: {existing_user.id})")
        except Exception as e:
            print(f"⚠ Failed to create default user: {e}")

        print("\nTables created:")
        print("  - users")
        print("  - devices")
        print("  - device_states")
        print("  - position_records")
        print("  - trips")
        print("  - geofences")
        print("  - alert_history")
        print("  - command_queue")
        print("  - user_device_access (association table)")
        
        print("\nPostGIS extension enabled: ✓")
        
        print("\n=== Database Initialization Complete ===\n")
        print("Next steps:")
        print("  1. Start the application: python main.py")
        print("  2. Access the dashboard")
        
        await db_service.close()
        
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        print("\nTroubleshooting:")
        print("  1. Ensure PostgreSQL is running")
        print("  2. Verify database credentials in .env file")
        print("  3. Check that the database exists")
        print("  4. Ensure PostGIS extension is available")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
