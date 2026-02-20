#!/bin/bash
# Quick Setup Script for Routario Platform
# Ubuntu/Debian

set -e

echo "=== Routario Platform - Quick Setup ==="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
    echo -e "${RED}Please do not run as root${NC}"
    exit 1
fi

echo -e "${YELLOW}Step 1: Installing system dependencies...${NC}"
sudo apt update
sudo apt install -y postgresql-17 postgresql-17-postgis-3 redis-server python3.13 python3.13-venv python3-pip

echo -e "${GREEN}✓ System dependencies installed${NC}"
echo ""

echo -e "${YELLOW}Step 2: Starting services...${NC}"
sudo systemctl start postgresql
sudo systemctl start redis-server
sudo systemctl enable postgresql
sudo systemctl enable redis-server

echo -e "${GREEN}✓ Services started${NC}"
echo ""

echo -e "${YELLOW}Step 3: Creating database...${NC}"
sudo -u postgres psql << EOF
-- Check if database exists
SELECT 'Database already exists' WHERE EXISTS (SELECT FROM pg_database WHERE datname = 'gps_platform')
UNION ALL
SELECT 'Creating database' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'gps_platform');

-- Create database if it doesn't exist
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_database WHERE datname = 'gps_platform') THEN
        CREATE DATABASE gps_platform;
    END IF;
END
\$\$;

-- Check if user exists
SELECT 'User already exists' WHERE EXISTS (SELECT FROM pg_roles WHERE rolname = 'gps_user')
UNION ALL
SELECT 'Creating user' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gps_user');

-- Create user if it doesn't exist
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gps_user') THEN
        CREATE USER gps_user WITH PASSWORD 'gps_password';
    END IF;
END
\$\$;

-- Grant database privileges
GRANT ALL PRIVILEGES ON DATABASE gps_platform TO gps_user;

-- Make gps_user owner of the database
ALTER DATABASE gps_platform OWNER TO gps_user;
EOF

# Grant schema privileges
sudo -u postgres psql gps_platform << EOF
-- Enable PostGIS
CREATE EXTENSION IF NOT EXISTS postgis;

-- Grant all privileges on public schema
GRANT ALL ON SCHEMA public TO gps_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO gps_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO gps_user;

-- Set default privileges for future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO gps_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO gps_user;

-- Make gps_user owner of public schema objects
REASSIGN OWNED BY postgres TO gps_user;
EOF

echo -e "${GREEN}✓ Database created${NC}"
echo ""

echo -e "${YELLOW}Step 4: Setting up Python environment...${NC}"
python3.13 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo -e "${GREEN}✓ Python environment ready${NC}"
echo ""

echo -e "${YELLOW}Step 5: Creating configuration...${NC}"
if [ ! -f .env ]; then
    cp .env.example .env
    echo -e "${GREEN}✓ Created .env file${NC}"
    echo -e "${YELLOW}⚠ Please edit .env and update SECRET_KEY before production use!${NC}"
else
    echo -e "${YELLOW}⚠ .env file already exists, skipping${NC}"
fi
echo ""

echo -e "${YELLOW}Step 6: Initializing database schema...${NC}"
python init_db.py

echo -e "${GREEN}✓ Database schema initialized${NC}"
echo ""

echo "=== Setup Complete! ==="
echo ""
echo "Next steps:"
echo "  1. Review and update .env file (especially SECRET_KEY)"
echo "  2. Start the application:"
echo "     source venv/bin/activate"
echo "     python main.py"
echo ""
echo "  3. Access API documentation:"
echo "     http://localhost:8000/docs"
echo ""
echo "  4. Configure your GPS devices to connect to:"
echo "     TCP: <your-server-ip>:5023"
echo "     UDP: <your-server-ip>:5024"
echo ""
echo "  5. Test with device simulator:"
echo "     python examples.py simulate"
echo ""
echo -e "${GREEN}Happy tracking!${NC}"
