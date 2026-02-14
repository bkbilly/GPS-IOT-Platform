# GPS IOT Platform

A simple yet powerful platform for real-time GPS tracking and IoT data management. Built with Python (FastAPI), PostgreSQL (PostGIS), and Redis.

## ✨ Features

 - Live Tracking: Real-time map updates via WebSockets.
 - Multi-Protocol: Support for Teltonika (TCP), GT06 (TCP), and H02 (UDP).
 - Smart Alerts: Instant notifications for speeding, idling, geofencing, and towing.
 - History Replay: Replay vehicle trips with detailed sensor data.
 - User Management: Admin panel to create users and assign specific devices.
 - Multi-Channel: Notifications via Telegram, Discord, Email, and more (via Apprise).

## 🚀 Quick Start

### Prerequisites

 - Python 3.10+
 - PostgreSQL with PostGIS
 - Redis

### 1. Setup
```bash
git clone [https://github.com/your-repo/gps-iot-platform.git](https://github.com/your-repo/gps-iot-platform.git)
cd gps-iot-platform
pip install -r requirements.txt
```

### 2. Configuration

Create a `.env` file and update your database and Redis settings:
```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/gps_db
REDIS_URL=redis://localhost:6379
SECRET_KEY=your_secret_key
```

### 3. Initialize & Run
```bash
# Create tables and default admin
python init_db.py

# Start the server
python main.py
```
 - Default Admin: `admin` / `admin_password`
 - Web UI: http://localhost:8000/web/login.html

## 📡 Default Ports

|    Service | Protocol | Port |
|------------|----------|------|
| Web Interface / API | HTTP | 8000 |
| GT06 Trackers | TCP | 5023 |
| H02 Trackers | UDP | 5024 |
| Teltonika Trackers | TCP | 5027 |

## 🛠️ Testing

Don't have a hardware tracker? Use our built-in simulator:
```bash
python teltonika_simulator.py
```

## 📖 API Documentation

Once running, visit:
 - Swagger UI: http://localhost:8000/docs
