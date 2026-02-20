-- Routario Platform - Database Setup Script
-- Run this as postgres superuser

-- Create database
CREATE DATABASE gps_platform;

-- Create user
CREATE USER gps_user WITH PASSWORD 'gps_password';

-- Grant database privileges
GRANT ALL PRIVILEGES ON DATABASE gps_platform TO gps_user;

-- Make gps_user the database owner
ALTER DATABASE gps_platform OWNER TO gps_user;

-- Connect to the database
\c gps_platform

-- Enable PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;

-- Grant schema privileges
GRANT ALL ON SCHEMA public TO gps_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO gps_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO gps_user;

-- Set default privileges for future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO gps_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO gps_user;

-- Transfer ownership of existing objects
REASSIGN OWNED BY postgres TO gps_user;

-- Verify setup
\du gps_user
\l gps_platform
\dx postgis

-- You should see:
-- 1. gps_user role listed
-- 2. gps_platform database owned by gps_user
-- 3. postgis extension installed

GRANT USAGE ON SCHEMA public TO gps_user;
GRANT CREATE ON SCHEMA public TO gps_user;
