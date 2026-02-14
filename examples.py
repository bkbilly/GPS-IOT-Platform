"""
Example Client Code - Testing the GPS/IoT Platform
"""
import asyncio
import aiohttp
import json
from datetime import datetime, timedelta
import random


# ==================== WebSocket Client Example ====================

async def websocket_client_example():
    """
    Example WebSocket client for receiving real-time updates
    """
    url = "ws://localhost:8000/ws/1"  # user_id = 1
    
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url) as ws:
            print("WebSocket connected")
            
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    
                    if data['type'] == 'position_update':
                        print(f"Position Update: Device {data['device_id']}")
                        print(f"  Location: {data['data']['latitude']}, {data['data']['longitude']}")
                        print(f"  Speed: {data['data']['speed']} km/h")
                        print(f"  Ignition: {data['data']['ignition']}")
                    
                    elif data['type'] == 'alert':
                        print(f"Alert: {data['data']['message']}")
                
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print(f"WebSocket error: {ws.exception()}")
                    break


# ==================== REST API Client Example ====================

class GPSPlatformClient:
    """Python client for GPS Platform API"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def get_devices(self, user_id: int):
        """Get all devices for user"""
        async with self.session.get(
            f"{self.base_url}/api/devices",
            params={"user_id": user_id}
        ) as resp:
            return await resp.json()
    
    async def get_device_state(self, device_id: int):
        """Get current device state"""
        async with self.session.get(
            f"{self.base_url}/api/devices/{device_id}/state"
        ) as resp:
            return await resp.json()
    
    async def get_position_history(
        self,
        device_id: int,
        start_time: datetime,
        end_time: datetime,
        max_points: int = 1000
    ):
        """Get position history"""
        async with self.session.post(
            f"{self.base_url}/api/positions/history",
            json={
                "device_id": device_id,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "max_points": max_points
            }
        ) as resp:
            return await resp.json()
    
    async def create_geofence(
        self,
        device_id: int,
        name: str,
        polygon: list,
        alert_on_enter: bool = False,
        alert_on_exit: bool = False
    ):
        """Create a geofence"""
        async with self.session.post(
            f"{self.base_url}/api/geofences",
            json={
                "device_id": device_id,
                "name": name,
                "polygon": polygon,
                "alert_on_enter": alert_on_enter,
                "alert_on_exit": alert_on_exit
            }
        ) as resp:
            return await resp.json()
    
    async def get_trips(
        self,
        device_id: int,
        start_date: datetime = None,
        end_date: datetime = None
    ):
        """Get trips for device"""
        params = {}
        if start_date:
            params['start_date'] = start_date.isoformat()
        if end_date:
            params['end_date'] = end_date.isoformat()
        
        async with self.session.get(
            f"{self.base_url}/api/devices/{device_id}/trips",
            params=params
        ) as resp:
            return await resp.json()
    
    async def send_command(
        self,
        device_id: int,
        command_type: str,
        payload: str
    ):
        """Send command to device"""
        async with self.session.post(
            f"{self.base_url}/api/commands",
            json={
                "device_id": device_id,
                "command_type": command_type,
                "payload": payload
            }
        ) as resp:
            return await resp.json()
    
    async def get_alerts(self, user_id: int, unread_only: bool = True):
        """Get alerts for user"""
        async with self.session.get(
            f"{self.base_url}/api/alerts",
            params={
                "user_id": user_id,
                "unread_only": unread_only
            }
        ) as resp:
            return await resp.json()


# ==================== GPS Device Simulator ====================

class GPSDeviceSimulator:
    """
    Simulate a GPS device sending data to the platform
    Useful for testing without real hardware
    """
    
    def __init__(self, host: str, port: int, imei: str, protocol: str = "gt06"):
        self.host = host
        self.port = port
        self.imei = imei
        self.protocol = protocol
        
        # Simulated position
        self.latitude = 37.7749  # San Francisco
        self.longitude = -122.4194
        self.speed = 0.0
        self.course = 0.0
        self.ignition = False
    
    async def connect_and_send(self, duration_seconds: int = 60, interval: int = 10):
        """
        Connect to server and send simulated positions
        
        Args:
            duration_seconds: How long to simulate
            interval: Seconds between position updates
        """
        reader, writer = await asyncio.open_connection(self.host, self.port)
        
        print(f"Connected to {self.host}:{self.port}")
        
        # Send login packet (GT06 example)
        login_packet = self._create_gt06_login()
        writer.write(login_packet)
        await writer.drain()
        
        print("Login packet sent")
        
        # Wait for login response
        response = await reader.read(1024)
        print(f"Login response: {response.hex()}")
        
        # Simulate movement
        start_time = asyncio.get_event_loop().time()
        
        while (asyncio.get_event_loop().time() - start_time) < duration_seconds:
            # Update simulated position
            self._update_position()
            
            # Create and send position packet
            position_packet = self._create_gt06_position()
            writer.write(position_packet)
            await writer.drain()
            
            print(f"Position sent: ({self.latitude:.6f}, {self.longitude:.6f}) "
                  f"Speed: {self.speed:.1f} km/h")
            
            # Wait for interval
            await asyncio.sleep(interval)
        
        writer.close()
        await writer.wait_closed()
        print("Disconnected")
    
    def _update_position(self):
        """Update simulated position (random walk)"""
        # Random movement
        self.latitude += random.uniform(-0.001, 0.001)
        self.longitude += random.uniform(-0.001, 0.001)
        
        # Random speed (0-60 km/h)
        self.speed = random.uniform(0, 60)
        
        # Random course (0-360 degrees)
        self.course = random.uniform(0, 360)
        
        # Random ignition
        if random.random() < 0.1:  # 10% chance to toggle
            self.ignition = not self.ignition
    
    def _create_gt06_login(self) -> bytes:
        """Create GT06 login packet"""
        # Simplified GT06 login packet
        packet = b'\x78\x78'  # Start bit
        packet += b'\x0D'     # Length
        packet += b'\x01'     # Protocol number (login)
        
        # IMEI (8 bytes)
        imei_int = int(self.imei) if self.imei.isdigit() else 123456789012345
        packet += imei_int.to_bytes(8, 'big')
        
        packet += b'\x00\x01'  # Serial number
        packet += b'\x00\x00'  # Checksum (simplified)
        packet += b'\x0D\x0A'  # End marker
        
        return packet
    
    def _create_gt06_position(self) -> bytes:
        """Create GT06 position packet (simplified)"""
        now = datetime.utcnow()
        
        packet = b'\x78\x78'  # Start bit
        packet += b'\x22'     # Length (simplified)
        packet += b'\x12'     # Protocol number (position)
        
        # Date/Time
        packet += bytes([
            now.year - 2000,
            now.month,
            now.day,
            now.hour,
            now.minute,
            now.second
        ])
        
        # GPS data (simplified - would need proper encoding)
        packet += b'\x08'  # Satellites
        
        # Course/Status
        course_int = int(self.course) & 0x03FF
        packet += course_int.to_bytes(2, 'big')
        
        # Latitude (simplified)
        lat_int = int(abs(self.latitude) * 1800000)
        packet += lat_int.to_bytes(4, 'big')
        
        # Longitude (simplified)
        lon_int = int(abs(self.longitude) * 1800000)
        packet += lon_int.to_bytes(4, 'big')
        
        # Speed
        packet += int(self.speed).to_bytes(1, 'big')
        
        # Status
        status = 0x01 if self.ignition else 0x00
        packet += status.to_bytes(1, 'big')
        
        packet += b'\x00\x01'  # Serial number
        packet += b'\x00\x00'  # Checksum (simplified)
        packet += b'\x0D\x0A'  # End marker
        
        return packet


# ==================== Example Usage ====================

async def example_api_usage():
    """Example of using the API client"""
    async with GPSPlatformClient() as client:
        # Get devices
        devices = await client.get_devices(user_id=1)
        print(f"Found {len(devices)} devices")
        
        if devices:
            device_id = devices[0]['id']
            
            # Get device state
            state = await client.get_device_state(device_id)
            print(f"Device state: {state}")
            
            # Get position history
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=24)
            
            history = await client.get_position_history(
                device_id,
                start_time,
                end_time
            )
            print(f"Position history: {len(history['features'])} points")
            
            # Create geofence (home)
            geofence = await client.create_geofence(
                device_id=device_id,
                name="Home",
                polygon=[
                    [-122.42, 37.78],
                    [-122.41, 37.78],
                    [-122.41, 37.77],
                    [-122.42, 37.77],
                    [-122.42, 37.78]
                ],
                alert_on_exit=True
            )
            print(f"Geofence created: {geofence}")
            
            # Get alerts
            alerts = await client.get_alerts(user_id=1)
            print(f"Unread alerts: {len(alerts)}")


async def example_device_simulation():
    """Example of simulating a GPS device"""
    simulator = GPSDeviceSimulator(
        host="localhost",
        port=5023,
        imei="123456789012345",
        protocol="gt06"
    )
    
    # Simulate for 5 minutes, sending position every 10 seconds
    await simulator.connect_and_send(duration_seconds=300, interval=10)


async def main():
    """Run examples"""
    print("=== GPS Platform Client Examples ===\n")
    
    # Choose example to run
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "api":
            print("Running API client example...")
            await example_api_usage()
        
        elif sys.argv[1] == "simulate":
            print("Running device simulator...")
            await example_device_simulation()
        
        elif sys.argv[1] == "websocket":
            print("Running WebSocket client...")
            await websocket_client_example()
    
    else:
        print("Usage:")
        print("  python examples.py api       - Test API client")
        print("  python examples.py simulate  - Simulate GPS device")
        print("  python examples.py websocket - WebSocket real-time updates")


if __name__ == "__main__":
    asyncio.run(main())
