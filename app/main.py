"""
FastAPI Application - GPS/IoT Platform
Thin entrypoint: app setup, lifespan, WebSocket, and internal callbacks.
All REST routes live in app/routes/.
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List, Optional, Any

import jwt
import redis.asyncio as redis
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings
from core.database import get_db, init_database
from core.alert_engine import get_alert_engine, offline_detection_task
from core.gateway import TCPServer, UDPServer, connection_manager
from models import Device, AlertHistory
from models.schemas import NormalizedPosition, WSMessageType
from protocols import ProtocolRegistry
from routes import ROUTE_REGISTRY

logger = logging.getLogger(__name__)


# ==================== Redis Pub/Sub ====================

class RedisPubSub:
    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        self.pubsub = None

    async def connect(self):
        if not self.redis_url:
            self.redis_url = get_settings().redis_url
        self.redis_client = await redis.from_url(self.redis_url, decode_responses=True)
        self.pubsub = self.redis_client.pubsub()
        logger.info("Redis connected for Pub/Sub")

    async def publish(self, channel: str, message: Dict[str, Any]):
        if self.redis_client:
            await self.redis_client.publish(channel, json.dumps(message))

    async def close(self):
        if self.pubsub:
            await self.pubsub.close()
        if self.redis_client:
            await self.redis_client.close()


redis_pubsub = RedisPubSub()


# ==================== WebSocket Manager ====================

class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.setdefault(user_id, []).append(websocket)
        logger.info(f"WebSocket connected for user {user_id}")

    def disconnect(self, user_id: int, websocket: WebSocket):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        logger.info(f"WebSocket disconnected for user {user_id}")

    async def broadcast_position_update(self, position: NormalizedPosition, device: Device):
        state_data = {}
        if device.state:
            state_data = {
                "total_odometer": device.state.total_odometer,
                "trip_odometer": device.state.trip_odometer,
                "is_moving": device.state.is_moving,
                "is_online": device.state.is_online,
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
                **state_data,
            },
        }
        await redis_pubsub.publish(f"device:{device.id}", message)

    async def broadcast_alert(self, alert: AlertHistory):
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
                "created_at": alert.created_at.isoformat(),
            },
        }
        await redis_pubsub.publish(f"device:{alert.device_id}", message)


ws_manager = WebSocketManager()


# ==================== Position / Command Callbacks ====================

async def process_position_callback(position: NormalizedPosition):
    try:
        db = get_db()
        success = await db.process_position(position)
        if not success:
            return
        device = await db.get_device_by_imei(position.imei)
        if not device or not device.state:
            return
        alert_engine = get_alert_engine()
        await alert_engine.process_position_alerts(position, device, device.state)
        await ws_manager.broadcast_position_update(position, device)
        logger.debug(f"Position processed: {device.name}")
    except Exception as e:
        logger.error(f"Position processing error: {e}", exc_info=True)


async def command_callback(imei: str, writer):
    try:
        db = get_db()
        device = await db.get_device_by_imei(imei)
        if not device:
            return
        commands = await db.get_pending_commands(device.id)
        for command in commands:
            decoder = ProtocolRegistry.get_decoder(device.protocol)
            if not decoder:
                continue
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


# ==================== Lifespan ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting GPS/IoT Platform...")
    settings = get_settings()

    await init_database(settings.database_url)

    redis_pubsub.redis_url = settings.redis_url
    await redis_pubsub.connect()

    alert_engine = get_alert_engine()
    alert_engine.set_alert_callback(handle_new_alert)

    protocols = ProtocolRegistry.get_all()
    for name, decoder in protocols.items():
        port = decoder.PORT
        protocol_type = getattr(decoder, "PROTOCOL_TYPE", "tcp").lower()
        if protocol_type == "udp":
            server = UDPServer(settings.udp_host, port, name, process_position_callback)
            asyncio.create_task(server.start())
            logger.info(f"Started UDP Server for {name} on port {port}")
        else:
            server = TCPServer(settings.tcp_host, port, name, process_position_callback, command_callback)
            asyncio.create_task(server.start())
            logger.info(f"Started TCP Server for {name} on port {port}")

    asyncio.create_task(offline_detection_task())
    logger.info("GPS/IoT Platform started successfully")

    yield

    logger.info("Shutting down GPS/IoT Platform...")
    db = get_db()
    await db.close()
    await redis_pubsub.close()
    logger.info("GPS/IoT Platform shutdown complete")


# ==================== App ====================

app = FastAPI(
    title="GPS/IoT Platform API",
    description="High-performance GPS tracking and IoT platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all auto-discovered routers
for router in ROUTE_REGISTRY:
    app.include_router(router)


# ==================== Root + WebSocket ====================

@app.get("/")
async def root():
    return {
        "status": "online",
        "version": "1.0.0",
        "protocols": ProtocolRegistry.list_protocols(),
        "online_devices": len(connection_manager.connections),
    }


@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await ws_manager.connect(user_id, websocket)
    r = await redis.from_url(get_settings().redis_url, decode_responses=True)
    pubsub = r.pubsub()
    try:
        db = get_db()
        devices = await db.get_user_devices(user_id)
        device_channels = [f"device:{device.id}" for device in devices]
        if device_channels:
            await pubsub.subscribe(*device_channels)

        async def listen_to_redis():
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        await websocket.send_text(message["data"])
                    except Exception as e:
                        logger.error(f"WS Send Error: {e}")
                        break

        async def listen_to_client():
            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                pass

        await asyncio.gather(listen_to_redis(), listen_to_client())
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
    finally:
        await pubsub.close()
        await r.close()
        ws_manager.disconnect(user_id, websocket)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, workers=1, loop="uvloop")
