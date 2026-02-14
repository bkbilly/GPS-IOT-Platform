import asyncio
import logging
import sys
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from config import get_settings
from database import init_database

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def reset_database():
    """
    Resets the database by:
    1. Connecting to the default 'postgres' database
    2. Terminating active connections to 'gps_platform'
    3. Dropping and Recreating 'gps_platform'
    4. Running the schema initialization
    """
    settings = get_settings()
    
    # We need to connect to the maintenance database ('postgres') 
    # to drop/create the target database ('gps_platform')
    target_db_name = settings.database_url.split("/")[-1]
    maintenance_db_url = settings.database_url.replace(f"/{target_db_name}", "/postgres")
    
    logger.info(f"Target Database: {target_db_name}")
    logger.info("Connecting to maintenance database to perform reset...")
    
    # engine with isolation_level="AUTOCOMMIT" is required for DROP/CREATE DATABASE
    engine = create_async_engine(maintenance_db_url, isolation_level="AUTOCOMMIT")
    
    try:
        async with engine.connect() as conn:
            # 1. Terminate existing connections
            logger.info(f"Terminating existing connections to {target_db_name}...")
            await conn.execute(text(f"""
                SELECT pg_terminate_backend(pg_stat_activity.pid)
                FROM pg_stat_activity
                WHERE pg_stat_activity.datname = '{target_db_name}'
                AND pid <> pg_backend_pid();
            """))
            
            # 2. Drop Database
            logger.info(f"Dropping database '{target_db_name}'...")
            await conn.execute(text(f"DROP DATABASE IF EXISTS {target_db_name}"))
            
            # 3. Create Database
            logger.info(f"Creating database '{target_db_name}'...")
            await conn.execute(text(f"CREATE DATABASE {target_db_name}"))
            
    except Exception as e:
        logger.error(f"Failed during database reset: {e}")
        logger.warning("\nIf this failed due to permissions:")
        logger.warning("1. Ensure your database user has CREATEDB privileges.")
        logger.warning("2. Or use the manual SQL steps in RESET_INSTRUCTIONS.md")
        await engine.dispose()
        sys.exit(1)
        
    await engine.dispose()
    logger.info("Database empty container created successfully.")
    
    # 4. Initialize Schema (Tables & Extensions)
    logger.info("Initializing schema (creating tables)...")
    try:
        # Connect to the NEWLY created database url
        db_service = await init_database(settings.database_url)
        await db_service.close()
        logger.info("✅ SUCCESS: Database has been reset and initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize schema: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(reset_database())
