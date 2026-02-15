"""
FastAPI Application - GPS/IoT Platform
REST API and WebSocket real-time updates
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
import redis.asyncio as redis
import json
import jwt

from models import Device, DeviceState, PositionRecord, Trip, Geofence, AlertHistory
from models.schemas import (
    DeviceCreate, DeviceResponse, DeviceStateResponse,
    PositionHistoryRequest, PositionHistoryResponse, PositionGeoJSON,
    TripResponse, TripGeoJSON, GeofenceCreate, GeofenceResponse,
    AlertResponse, CommandCreate, CommandResponse,
    WSMessage, WSMessageType, NormalizedPosition, UserCreate, UserResponse, UserUpdate, DeviceStatistics,
    UserLogin, Token
)
from core.database import get_db, init_database
from protocols import ProtocolRegistry
from core.alert_engine import get_alert_engine, offline_detection_task
from core.gateway import TCPServer, UDPServer, connection_manager
from core.config import get_settings

import uvicorn

from sqlalchemy import select, insert, update, delete, and_
from models import User, Device, user_device_association



logger = logging.getLogger(__name__)


# ==================== Startup/Shutdown Events ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown"""
    # Startup
    logger.info("Starting GPS/IoT Platform...")
    settings = get_settings()
    
    await init_database(settings.database_url)
    
    redis_pubsub.redis_url = settings.redis_url
    await redis_pubsub.connect()

    alert_engine = get_alert_engine()
    alert_engine.set_alert_callback(handle_new_alert)
    
    # Dynamic Protocol Server Startup
    protocols = ProtocolRegistry.get_all()
    for name, decoder in protocols.items():
        port = decoder.PORT
        protocol_type = getattr(decoder, 'PROTOCOL_TYPE', 'tcp').lower()

        if protocol_type == 'udp':
            server = UDPServer(settings.udp_host, port, name, process_position_callback)
            asyncio.create_task(server.start())
            logger.info(f"Started UDP Server for {name} on port {port}")
        else:
            server = TCPServer(settings.tcp_host, port, name, process_position_callback, command_callback)
            asyncio.create_task(server.start())
            logger.info(f"Started TCP Server for {name} on port {port}")

    asyncio.create_task(offline_detection_task())
    logger.info("GPS/IoT Platform started successfully")
    
    # Yield control to the application
    yield
    
    # Shutdown
    logger.info("Shutting down GPS/IoT Platform...")
    db = get_db()
    await db.close()
    await redis_pubsub.close()
    logger.info("GPS/IoT Platform shutdown complete")


# ==================== FastAPI App ====================

app = FastAPI(
    title="GPS/IoT Platform API",
    description="High-performance GPS tracking and IoT platform",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== Redis Pub/Sub for WebSockets ====================

class RedisPubSub:
    """Redis Pub/Sub for multi-worker WebSocket support"""
    
    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        self.pubsub = None
    
    async def connect(self):
        """Connect to Redis"""
        if not self.redis_url:
            self.redis_url = get_settings().redis_url
            
        self.redis_client = await redis.from_url(self.redis_url, decode_responses=True)
        self.pubsub = self.redis_client.pubsub()
        logger.info("Redis connected for Pub/Sub")
    
    async def publish(self, channel: str, message: Dict[str, Any]):
        """Publish message to channel"""
        if self.redis_client:
            await self.redis_client.publish(channel, json.dumps(message))
            
    async def close(self):
        """Close connections"""
        if self.pubsub:
            await self.pubsub.close()
        if self.redis_client:
            await self.redis_client.close()


redis_pubsub = RedisPubSub()


# ==================== WebSocket Connection Manager ====================

class WebSocketManager:
    """Manages WebSocket connections per user"""
    
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}  # user_id -> [websockets]
    
    async def connect(self, user_id: int, websocket: WebSocket):
        """Register new WebSocket connection"""
        await websocket.accept()
        
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        
        self.active_connections[user_id].append(websocket)
        logger.info(f"WebSocket connected for user {user_id}")
    
    def disconnect(self, user_id: int, websocket: WebSocket):
        """Remove WebSocket connection"""
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        
        logger.info(f"WebSocket disconnected for user {user_id}")
    
    async def broadcast_position_update(self, position: NormalizedPosition, device: Device):
        """Broadcast position update to all users with access to device"""
        # Get the device state to include odometer
        state_data = {}
        if device.state:
            state_data = {
                "total_odometer": device.state.total_odometer,
                "trip_odometer": device.state.trip_odometer,
                "is_moving": device.state.is_moving,
                "is_online": device.state.is_online
            }
        
        message = {
            "type": WSMessageType.POSITION_UPDATE.value,
            "device_id": device.id,
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "last_latitude": position.latitude,
                "last_longitude": position.longitude,
                "last_altitude": position.altitude,
                "satellites": position.satellites,
                "last_speed": position.speed,
                "last_course": position.course,
                "ignition_on": position.ignition if position.ignition is not None else False,
                "last_update": position.device_time.isoformat(),
                **state_data  # Include odometer and other state data
            }
        }
        await redis_pubsub.publish(f"device:{device.id}", message)

    async def broadcast_alert(self, alert: AlertHistory):
        """Broadcast alert to relevant device channel"""
        message = {
            "type": WSMessageType.ALERT.value,
            "device_id": alert.device_id,
            "timestamp": alert.created_at.isoformat(),
            "data": {
                "id": alert.id,
                "type": alert.alert_type,
                "severity": alert.severity,
                "message": alert.message,
                "alert_metadata": alert.alert_metadata,
                "created_at": alert.created_at.isoformat()
            }
        }
        await redis_pubsub.publish(f"device:{alert.device_id}", message)

ws_manager = WebSocketManager()


# ==================== Position Processing Callback ====================

async def process_position_callback(position: NormalizedPosition):
    """Callback for processing incoming GPS positions"""
    try:
        db = get_db()
        success = await db.process_position(position)
        if not success: return
        
        device = await db.get_device_by_imei(position.imei)
        if not device or not device.state: return
        
        alert_engine = get_alert_engine()
        await alert_engine.process_position_alerts(position, device, device.state)
        await ws_manager.broadcast_position_update(position, device)
        
        logger.debug(f"Position processed: {device.name}")
    except Exception as e:
        logger.error(f"Position processing error: {e}", exc_info=True)


async def command_callback(imei: str, writer):
    """Callback for sending pending commands"""
    try:
        db = get_db()
        device = await db.get_device_by_imei(imei)
        if not device: return
        
        commands = await db.get_pending_commands(device.id)
        for command in commands:
            decoder = ProtocolRegistry.get_decoder(device.protocol)
            if not decoder: continue
            
            command_bytes = await decoder.encode_command(
                command.command_type, {"payload": command.payload}
            )
            
            if command_bytes:
                writer.write(command_bytes)
                await writer.drain()
                await db.mark_command_sent(command.id)
                logger.info(f"Command sent to {device.name}: {command.command_type}")
    except Exception as e:
        logger.error(f"Command callback error: {e}", exc_info=True)

async def handle_new_alert(alert: AlertHistory):
    try:
        await ws_manager.broadcast_alert(alert)
    except Exception as e:
        logger.error(f"Failed to broadcast alert: {e}")


# ==================== REST API Endpoints ====================

@app.get("/")
async def root():
    return {
        "status": "online",
        "version": "1.0.0",
        "protocols": ProtocolRegistry.list_protocols(),
        "online_devices": len(connection_manager.connections)
    }

# ==================== User Endpoints ====================

@app.post("/api/login", response_model=Token)
async def login(form_data: UserLogin):
    db = get_db()
    user = await db.authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    
    settings = get_settings()
    token_data = {"sub": str(user.id), "name": user.username}
    # Using python-jose for encoding
    token = jwt.encode(token_data, settings.secret_key, algorithm=settings.algorithm)
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user.id,
        "username": user.username
    }

@app.get("/api/users", response_model=List[UserResponse])
async def get_all_users():
    """Get all users (Admin)"""
    db = get_db()
    async with db.get_session() as session:
        result = await session.execute(select(User))
        return result.scalars().all()

@app.post("/api/users", response_model=UserResponse)
async def create_user(user_data: UserCreate):
    db = get_db()
    user = await db.create_user(user_data)
    return user

@app.get("/api/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: int):
    db = get_db()
    user = await db.get_user(user_id)
    if not user: raise HTTPException(status_code=404, detail="User not found")
    return user

@app.put("/api/users/{user_id}", response_model=UserResponse)
async def update_user(user_id: int, user_data: UserUpdate):
    db = get_db()
    user = await db.update_user(user_id, user_data)
    if not user: raise HTTPException(status_code=404, detail="User not found")
    return user

@app.delete("/api/users/{user_id}")
async def delete_user(user_id: int):
    """Delete a user (Admin only)"""
    db = get_db()
    async with db.get_session() as session:
        await session.execute(delete(User).where(User.id == user_id))
    return {"status": "deleted"}

@app.post("/api/users/{user_id}/devices")
async def assign_device(user_id: int, device_id: int = Query(...), action: str = Query('add')):
    """Assign or remove a device from a user"""
    db = get_db()
    
    async with db.get_session() as session:
        if action == 'add':
            # Check if exists
            exists = await session.execute(
                user_device_association.select().where(
                    and_(
                        user_device_association.c.user_id == user_id,
                        user_device_association.c.device_id == device_id
                    )
                )
            )
            if not exists.scalar_one_or_none():
                await session.execute(
                    user_device_association.insert().values(user_id=user_id, device_id=device_id, access_level='user')
                )
        elif action == 'remove':
            await session.execute(
                user_device_association.delete().where(
                    and_(
                        user_device_association.c.user_id == user_id,
                        user_device_association.c.device_id == device_id
                    )
                )
            )
            
    return {"status": "success"}

# ==================== Device Endpoints ====================

@app.get("/api/devices/all", response_model=List[DeviceResponse])
async def get_all_devices():
    """Get ALL devices in the system (Admin)"""
    db = get_db()
    async with db.get_session() as session:
        result = await session.execute(select(Device))
        return result.scalars().all()

@app.get("/api/devices", response_model=List[DeviceResponse])
async def get_devices(user_id: int = Query(..., description="User ID")):
    db = get_db()
    devices = await db.get_user_devices(user_id)
    return devices

@app.get("/api/devices/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: int):
    db = get_db()
    device = await db.get_device_by_id(device_id)
    if not device: raise HTTPException(status_code=404, detail="Device not found")
    return device

@app.get("/api/devices/{device_id}/state", response_model=DeviceStateResponse)
async def get_device_state(device_id: int):
    db = get_db()
    device = await db.get_device_by_id(device_id)
    if not device or not device.state: raise HTTPException(status_code=404, detail="Device state not found")
    return device.state

@app.post("/api/positions/history", response_model=PositionHistoryResponse)
async def get_position_history(request: PositionHistoryRequest):
    db = get_db()
    positions = await db.get_position_history(
        request.device_id, request.start_time, request.end_time, request.max_points, request.order
    )
    
    features = []
    total_distance = 0.0
    max_speed = 0.0
    
    for i, pos in enumerate(positions):
        if i > 0:
            prev = positions[i-1]
            async with db.get_session() as session:
                distance_km = await db._calculate_distance(session, prev.latitude, prev.longitude, pos.latitude, pos.longitude)
                total_distance += distance_km
        if pos.speed: max_speed = max(max_speed, pos.speed)
        
        feature = PositionGeoJSON(
            type="Feature",
            geometry={"type": "Point", "coordinates": [pos.longitude, pos.latitude]},
            properties={
                "speed": pos.speed, 
                "course": pos.course, 
                "ignition": pos.ignition, 
                "time": pos.device_time.isoformat(), 
                "altitude": pos.altitude,
                "satellites": pos.satellites,
                "sensors": pos.sensors
            }
        )
        features.append(feature)
    
    duration_minutes = 0
    if positions:
        t1 = positions[0].device_time
        t2 = positions[-1].device_time
        duration = abs((t2 - t1).total_seconds()) / 60
        duration_minutes = int(duration)
    
    return PositionHistoryResponse(
        type="FeatureCollection", features=features,
        summary={"total_distance_km": round(total_distance, 2), "duration_minutes": duration_minutes, "max_speed": round(max_speed, 1)}
    )

@app.get("/api/devices/{device_id}/trips", response_model=List[TripResponse])
async def get_device_trips(device_id: int, start_date: Optional[datetime] = Query(None), end_date: Optional[datetime] = Query(None)):
    db = get_db()
    if not start_date: start_date = datetime.utcnow() - timedelta(days=7)
    if not end_date: end_date = datetime.utcnow()
    trips = await db.get_device_trips(device_id, start_date, end_date)
    return trips

@app.post("/api/geofences", response_model=GeofenceResponse)
async def create_geofence(geofence: GeofenceCreate):
    db = get_db()
    return await db.create_geofence(geofence.model_dump())

@app.get("/api/alerts", response_model=List[AlertResponse])
async def get_alerts(user_id: int = Query(...), unread_only: bool = Query(False)):
    db = get_db()
    return await db.get_unread_alerts(user_id) if unread_only else await db.get_user_alerts(user_id)

@app.post("/api/alerts/{alert_id}/read")
async def mark_alert_read(alert_id: int):
    """Mark alert as read"""
    db = get_db()
    success = await db.mark_alert_read(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "success"}

@app.delete("/api/alerts/{alert_id}")
async def delete_alert(alert_id: int):
    """Delete an alert from history"""
    db = get_db()
    success = await db.delete_alert(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "deleted"}

@app.post("/api/devices")
async def create_device(device_data: DeviceCreate, user_id: int = Query(1)):
    db = get_db()
    existing = await db.get_device_by_imei(device_data.imei)
    if existing: raise HTTPException(status_code=400, detail="IMEI already exists")
    device = await db.create_device(device_data)
    await db.add_device_to_user(user_id, device.id)
    return device

@app.put("/api/devices/{device_id}")
async def update_device(device_id: int, device_data: DeviceCreate, new_odometer: Optional[float] = Query(None)):
    """Update device - properly handles config with None values for disabled alerts"""
    logger.info(f"Updating device {device_id}")
    logger.info(f"Received config: {device_data.config.model_dump()}")
    
    db = get_db()
    device = await db.update_device(device_id, device_data)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Update odometer if provided
    if new_odometer is not None:
        async with db.get_session() as session:
            await session.execute(
                update(DeviceState)
                .where(DeviceState.device_id == device_id)
                .values(total_odometer=new_odometer)
            )
        logger.info(f"Updated odometer to {new_odometer} km")
    
    logger.info(f"Saved config: {device.config}")
    return device

@app.delete("/api/devices/{device_id}")
async def delete_device(device_id: int):
    db = get_db()
    success = await db.delete_device(device_id)
    if not success: raise HTTPException(status_code=404, detail="Device not found")
    return {"status": "deleted"}

@app.get("/api/devices/{device_id}/statistics")
async def get_device_statistics(device_id: int, start_date: Optional[datetime] = Query(None), end_date: Optional[datetime] = Query(None)):
    db = get_db()
    if not start_date: start_date = datetime.utcnow() - timedelta(days=30)
    if not end_date: end_date = datetime.utcnow()
    return await db.get_device_statistics(device_id, start_date, end_date)


@app.get("/api/devices/{device_id}/command-support")
async def check_command_support(device_id: int):
    """
    Check if device protocol supports commands and get available commands.
    """
    db = get_db()
    device = await db.get_device_by_id(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    decoder = ProtocolRegistry.get_decoder(device.protocol)
    if not decoder:
        return {
            "supports_commands": False,
            "available_commands": [],
            "protocol": device.protocol,
            "command_info": {}
        }
    
    supports_commands = False
    available_commands = []
    command_info = {}
    
    # Try to get available commands from decoder
    if hasattr(decoder, 'get_available_commands'):
        try:
            available_commands = decoder.get_available_commands()
            supports_commands = len(available_commands) > 0
            
            if hasattr(decoder, 'get_command_info'):
                for cmd in available_commands:
                    command_info[cmd] = decoder.get_command_info(cmd)
        except Exception as e:
            print(f"Error getting available commands: {e}")
    else:
        # Fallback to testing common command types
        test_commands = ["reset", "interval", "reboot", "custom"]
        for cmd_type in test_commands:
            try:
                result = await decoder.encode_command(cmd_type, {})
                if result and len(result) > 0:
                    supports_commands = True
                    available_commands.append(cmd_type)
            except:
                pass
    
    return {
        "supports_commands": supports_commands,
        "available_commands": available_commands,
        "protocol": device.protocol,
        "command_info": command_info
    }


@app.post("/api/devices/{device_id}/command/preview")
async def preview_command(device_id: int, command_data: dict):
    """
    Preview what a command will look like when encoded.
    Shows hex output before sending.
    """
    db = get_db()
    device = await db.get_device_by_id(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    decoder = ProtocolRegistry.get_decoder(device.protocol)
    if not decoder:
        raise HTTPException(status_code=400, detail="Protocol not found")
    
    command_type = command_data.get('command_type', '')
    payload = command_data.get('payload', '')
    
    try:
        encoded = await decoder.encode_command(
            command_type,
            {"payload": payload} if payload else {}
        )
        
        if not encoded or len(encoded) == 0:
            raise HTTPException(
                status_code=400,
                detail="Command could not be encoded"
            )
        
        # ASCII representation
        try:
            ascii_repr = encoded.decode('ascii', errors='replace')
        except:
            ascii_repr = "Non-ASCII binary data"
        
        return {
            "hex": encoded.hex(),
            "bytes": len(encoded),
            "ascii": ascii_repr,
            "success": True
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Command encoding failed: {str(e)}"
        )


@app.post("/api/devices/{device_id}/command")
async def send_command(device_id: int, command: CommandCreate):
    """
    Queue a command to be sent to device.
    Enhanced version with validation and preview.
    """
    db = get_db()
    
    # Verify device exists
    device = await db.get_device_by_id(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Verify protocol supports commands
    decoder = ProtocolRegistry.get_decoder(device.protocol)
    if not decoder:
        raise HTTPException(status_code=400, detail="Protocol not found")
    
    # Test encode to ensure it's supported
    try:
        test_bytes = await decoder.encode_command(
            command.command_type,
            {"payload": command.payload} if command.payload else {}
        )
        
        if not test_bytes or len(test_bytes) == 0:
            raise HTTPException(
                status_code=400,
                detail=f"Protocol {device.protocol} does not support '{command.command_type}' command"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Command encoding failed: {str(e)}"
        )
    
    # Queue the command
    command.device_id = device_id
    result = await db.create_command(command)
    
    # Add the encoded preview to the response
    if hasattr(result, '__dict__'):
        result_dict = result.__dict__.copy()
    else:
        result_dict = dict(result)
    result_dict['encoded_preview'] = test_bytes.hex()
    
    return result_dict


@app.get("/api/devices/{device_id}/commands")
async def get_device_commands(device_id: int, status: str = None):
    """
    Get command history for a device.
    
    Args:
        device_id: Device ID
        status: Optional filter by status (pending, sent, failed, expired)
    """
    db = get_db()
    device = await db.get_device_by_id(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    commands = await db.get_device_commands(device_id, status=status)
    return commands



# ==================== WebSocket Endpoint ====================

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await ws_manager.connect(user_id, websocket)
    r = await redis.from_url(get_settings().redis_url, decode_responses=True)
    pubsub = r.pubsub()
    try:
        db = get_db()
        devices = await db.get_user_devices(user_id)
        device_channels = [f"device:{device.id}" for device in devices]
        if device_channels: await pubsub.subscribe(*device_channels)
            
        async def listen_to_redis():
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    try: await websocket.send_text(message['data'])
                    except Exception as e:
                        logger.error(f"WS Send Error: {e}")
                        break

        async def listen_to_client():
            try:
                while True: await websocket.receive_text()
            except WebSocketDisconnect: pass
                
        await asyncio.gather(listen_to_redis(), listen_to_client())
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
    finally:
        await pubsub.close()
        await r.close()
        ws_manager.disconnect(user_id, websocket)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, workers=1, loop="uvloop")