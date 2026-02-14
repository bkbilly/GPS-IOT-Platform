"""
Database Models - GPS/IoT Platform
Optimized for PostgreSQL + PostGIS with async SQLAlchemy 2.0
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from enum import Enum

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Float, 
    ForeignKey, Table, JSON, Index, Text, BigInteger, Interval
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID
from geoalchemy2 import Geography, Geometry
from geoalchemy2.shape import to_shape, from_shape
import uuid


class Base(DeclarativeBase):
    """Base class for all models"""
    pass


# Many-to-Many: Users <-> Devices
user_device_association = Table(
    'user_device_access',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('device_id', Integer, ForeignKey('devices.id', ondelete='CASCADE'), primary_key=True),
    Column('access_level', String(20), default='viewer'),  # viewer, manager, admin
    Column('created_at', DateTime, default=datetime.utcnow)
)


class User(Base):
    """User account with notification preferences"""
    __tablename__ = 'users'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Notification channels (Apprise URLs)
    notification_channels: Mapped[Dict] = mapped_column(
        JSONB, 
        default={
            "telegram": None,  # "tgram://bot_token/chat_id"
            "email": None,     # "mailto://user:pass@smtp.server"
            "slack": None,     # "slack://token_a/token_b/token_c"
            "discord": None,   # "discord://webhook_id/webhook_token"
        }
    )
    
    # Preferences
    timezone: Mapped[str] = mapped_column(String(50), default='UTC')
    language: Mapped[str] = mapped_column(String(10), default='en')
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    devices: Mapped[List["Device"]] = relationship(
        secondary=user_device_association,
        back_populates="users"
    )
    alert_history: Mapped[List["AlertHistory"]] = relationship(back_populates="user")


class Device(Base):
    """GPS Device/Tracker configuration"""
    __tablename__ = 'devices'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    imei: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    protocol: Mapped[str] = mapped_column(String(50), nullable=False)  # gt06, teltonika, etc.
    
    # Vehicle/Asset info
    vehicle_type: Mapped[Optional[str]] = mapped_column(String(50))
    license_plate: Mapped[Optional[str]] = mapped_column(String(20))
    vin: Mapped[Optional[str]] = mapped_column(String(17))
    
    # Device configuration (JSONB for flexibility)
    config: Mapped[Dict] = mapped_column(
        JSONB,
        default={
            "offline_timeout_hours": 24,
            "speed_tolerance": 5,  # km/h for speeding alerts
            "idle_timeout_minutes": 10,
            "sensors": {
                # Custom sensor formulas: "fuel": "adc1 * 0.5"
            },
            "maintenance": {
                "oil_change_km": 10000,
                "tire_rotation_km": 8000,
            }
        }
    )
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    users: Mapped[List["User"]] = relationship(
        secondary=user_device_association,
        back_populates="devices"
    )
    state: Mapped["DeviceState"] = relationship(back_populates="device", uselist=False)
    positions: Mapped[List["PositionRecord"]] = relationship(back_populates="device")
    trips: Mapped[List["Trip"]] = relationship(back_populates="device")
    geofences: Mapped[List["Geofence"]] = relationship(back_populates="device")
    commands: Mapped[List["CommandQueue"]] = relationship(back_populates="device")
    
    __table_args__ = (
        Index('idx_device_imei', 'imei'),
        Index('idx_device_protocol', 'protocol'),
    )


class DeviceState(Base):
    """Current state machine for each device"""
    __tablename__ = 'device_states'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey('devices.id', ondelete='CASCADE'), unique=True)
    
    # Last known position (PostGIS Geography for accurate distance in meters)
    last_position: Mapped[Optional[str]] = mapped_column(
        Geography(geometry_type='POINT', srid=4326),
        nullable=True
    )
    last_latitude: Mapped[Optional[float]] = mapped_column(Float)
    last_longitude: Mapped[Optional[float]] = mapped_column(Float)
    last_altitude: Mapped[Optional[float]] = mapped_column(Float)
    last_speed: Mapped[Optional[float]] = mapped_column(Float)  # km/h
    last_course: Mapped[Optional[float]] = mapped_column(Float)  # degrees
    last_address: Mapped[Optional[str]] = mapped_column(Text)  # Reverse geocoded
    
    # Status flags
    ignition_on: Mapped[bool] = mapped_column(Boolean, default=False)
    is_moving: Mapped[bool] = mapped_column(Boolean, default=False)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Odometer (km)
    total_odometer: Mapped[float] = mapped_column(Float, default=0.0)
    trip_odometer: Mapped[float] = mapped_column(Float, default=0.0)
    
    # Timestamps
    last_update: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    last_ignition_on: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_ignition_off: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    # Alert hysteresis (prevent alert spam)
    alert_states: Mapped[Dict] = mapped_column(
        JSONB,
        default={
            "idling_since": None,      # ISO timestamp or null
            "speeding_since": None,
            "offline_alerted": False,
            "towing_alerted": False,
        }
    )
    
    # Current trip ID (if active)
    active_trip_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey('trips.id'), nullable=True)
    
    # Relationship
    device: Mapped["Device"] = relationship(back_populates="state")
    
    __table_args__ = (
        Index('idx_device_state_last_update', 'last_update'),
        Index('idx_device_state_position', 'last_position', postgresql_using='gist'),
    )


class PositionRecord(Base):
    """GPS Position History - Partitioned by time"""
    __tablename__ = 'position_records'
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey('devices.id', ondelete='CASCADE'), index=True)
    
    # Spatial data (Geography for meter-based calculations)
    position: Mapped[str] = mapped_column(
        Geography(geometry_type='POINT', srid=4326),
        nullable=False
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    altitude: Mapped[Optional[float]] = mapped_column(Float)
    
    # Motion data
    speed: Mapped[Optional[float]] = mapped_column(Float)  # km/h
    course: Mapped[Optional[float]] = mapped_column(Float)  # degrees
    
    # GPS metadata
    satellites: Mapped[Optional[int]] = mapped_column(Integer)
    hdop: Mapped[Optional[float]] = mapped_column(Float)
    
    # Device state at this point
    ignition: Mapped[Optional[bool]] = mapped_column(Boolean)
    
    # Sensor data (flexible JSONB)
    sensors: Mapped[Optional[Dict]] = mapped_column(JSONB)
    
    # Timestamps
    device_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    server_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationship
    device: Mapped["Device"] = relationship(back_populates="positions")
    
    __table_args__ = (
        Index('idx_position_device_time', 'device_id', 'device_time'),
        Index('idx_position_spatial', 'position', postgresql_using='gist'),
        # Partition by month (requires manual setup in Alembic)
        # {'postgresql_partition_by': 'RANGE (device_time)'}
    )


class Trip(Base):
    """Trip representation (ignition ON to OFF)"""
    __tablename__ = 'trips'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey('devices.id', ondelete='CASCADE'), index=True)
    
    # Trip path (PostGIS LineString)
    path_geom: Mapped[Optional[str]] = mapped_column(
        Geometry(geometry_type='LINESTRING', srid=4326),
        nullable=True
    )
    
    # Trip metadata
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    start_latitude: Mapped[float] = mapped_column(Float)
    start_longitude: Mapped[float] = mapped_column(Float)
    start_address: Mapped[Optional[str]] = mapped_column(Text)
    
    end_latitude: Mapped[Optional[float]] = mapped_column(Float)
    end_longitude: Mapped[Optional[float]] = mapped_column(Float)
    end_address: Mapped[Optional[str]] = mapped_column(Text)
    
    # Statistics
    distance_km: Mapped[float] = mapped_column(Float, default=0.0)
    max_speed: Mapped[Optional[float]] = mapped_column(Float)
    avg_speed: Mapped[Optional[float]] = mapped_column(Float)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    
    # Relationship
    device: Mapped["Device"] = relationship(back_populates="trips")
    
    __table_args__ = (
        Index('idx_trip_device_start', 'device_id', 'start_time'),
        Index('idx_trip_path', 'path_geom', postgresql_using='gist'),
    )


class Geofence(Base):
    """Polygonal geofences for alerts"""
    __tablename__ = 'geofences'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[Optional[int]] = mapped_column(
        Integer, 
        ForeignKey('devices.id', ondelete='CASCADE'), 
        nullable=True  # NULL = global geofence
    )
    
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    
    # Polygon geometry (Geometry for geofence checks)
    polygon: Mapped[str] = mapped_column(
        Geometry(geometry_type='POLYGON', srid=4326),
        nullable=False
    )
    
    # Alert configuration
    alert_on_enter: Mapped[bool] = mapped_column(Boolean, default=False)
    alert_on_exit: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Metadata
    color: Mapped[str] = mapped_column(String(7), default='#3388ff')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationship
    device: Mapped[Optional["Device"]] = relationship(back_populates="geofences")
    
    __table_args__ = (
        Index('idx_geofence_polygon', 'polygon', postgresql_using='gist'),
    )


class AlertHistory(Base):
    """Alert event history"""
    __tablename__ = 'alert_history'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id', ondelete='CASCADE'), index=True)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey('devices.id', ondelete='CASCADE'), index=True)
    
    # Alert details
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)  # speeding, idling, geofence, etc.
    severity: Mapped[str] = mapped_column(String(20), default='info')  # info, warning, critical
    message: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Location context
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    address: Mapped[Optional[str]] = mapped_column(Text)
    
    # Additional data
    alert_metadata: Mapped[Optional[Dict]] = mapped_column(JSONB)
    
    # Status
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    # Relationships
    user: Mapped["User"] = relationship(back_populates="alert_history")
    
    __table_args__ = (
        Index('idx_alert_user_time', 'user_id', 'created_at'),
        Index('idx_alert_device_time', 'device_id', 'created_at'),
    )


class CommandQueue(Base):
    """GPRS downlink command queue"""
    __tablename__ = 'command_queue'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey('devices.id', ondelete='CASCADE'), index=True)
    
    # Command payload
    command_type: Mapped[str] = mapped_column(String(50), nullable=False)  # custom, reset, interval, etc.
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # Hex or ASCII
    
    # Status tracking
    status: Mapped[str] = mapped_column(
        String(20), 
        default='pending'  # pending, sent, acked, failed, timeout
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    acked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    # Retry logic
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    
    # Response
    response: Mapped[Optional[str]] = mapped_column(Text)
    
    # Relationship
    device: Mapped["Device"] = relationship(back_populates="commands")
    
    __table_args__ = (
        Index('idx_command_device_status', 'device_id', 'status'),
    )
