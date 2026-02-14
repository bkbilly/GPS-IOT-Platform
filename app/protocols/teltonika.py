import struct
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, Union
import logging
from models.schemas import NormalizedPosition
from . import BaseProtocolDecoder, ProtocolRegistry

logger = logging.getLogger(__name__)

@ProtocolRegistry.register("teltonika")
class TeltonikaDecoder(BaseProtocolDecoder):
    PORT = 5027
    
    IO_MAP = {
        1: 'din1', 2: 'din2', 3: 'din3', 4: 'din4', 9: 'adc1', 10: 'adc2', 11: 'iccid',
        12: 'fuel_used', 13: 'fuel_consumption', 16: 'odometer', 17: 'axisX', 18: 'axisY', 19: 'axisZ',
        21: 'gsm_signal', 24: 'speed', 30: 'fault_count', 31: 'engine_load', 32: 'coolant_temp', 36: 'rpm',
        66: 'external_voltage', 67: 'battery_voltage', 68: 'battery_current', 69: 'gnss_status', 70: 'pcb_temp',
        72: 'temp1', 73: 'temp2', 74: 'temp3', 75: 'temp4', 80: 'data_mode', 81: 'obd_speed', 82: 'throttle',
        83: 'fuel_used_obd', 84: 'fuel_level_obd', 85: 'rpm_obd', 87: 'odometer_obd', 89: 'fuel_level_percent',
        113: 'battery_level_percent', 115: 'engine_temp', 179: 'din_out1', 180: 'din_out2', 181: 'pdop',
        182: 'hdop', 199: 'trip_odometer', 200: 'sleep_mode', 205: 'cid2g', 206: 'lac', 239: 'ignition',
        240: 'movement', 241: 'gsm_operator', 244: 'roaming', 636: 'cid4g', 662: 'door'
    }

    IO_MULTIPLIERS = {
        9: 0.001, 10: 0.001, 12: 0.001, 13: 0.01, 21: 1, 24: 1.852, 25: 0.01, 26: 0.01, 27: 0.01, 28: 0.01,
        66: 0.001, 67: 0.001, 68: 0.001, 70: 0.1, 72: 0.1, 73: 0.1, 74: 0.1, 75: 0.1, 83: 0.1, 84: 0.1,
        110: 0.1, 115: 0.1, 181: 0.1, 182: 0.1, 701: 0.01, 702: 0.01, 703: 0.01, 704: 0.01
    }

    async def decode(self, data: bytes, client_info: Dict[str, Any], known_imei: Optional[str] = None) -> Tuple[Union[NormalizedPosition, Dict[str, Any], None], int]:
        try:
            if len(data) >= 4 and data[0:4] == b'\x00\x00\x00\x00':
                if len(data) < 8: return None, 0
                data_length = struct.unpack('>I', data[4:8])[0]
                total_len = 8 + data_length + 4
                if len(data) < total_len: return None, 0
                packet_data = data[8:8+data_length]
                consumed = total_len
                if len(packet_data) < 2: return None, consumed
                codec_id = packet_data[0]
                if codec_id == 0x08:
                    decoded = await self._decode_codec8(packet_data[2:], known_imei)
                    return decoded, consumed
                return None, consumed
            elif len(data) >= 2:
                imei_len = struct.unpack('>H', data[0:2])[0]
                if imei_len == 0: return None, 1 if len(data) >= 4 else 0
                if len(data) >= imei_len + 2:
                    try:
                        imei = data[2:2+imei_len].decode('ascii')
                        logger.info(f"Teltonika Login: {imei}")
                        return {"event": "login", "imei": imei, "response": b'\x01'}, imei_len + 2
                    except UnicodeDecodeError: return None, 1
                return None, 0
            return None, 0
        except Exception as e:
            logger.error(f"Teltonika Decode error: {e}")
            return None, 1

    async def _decode_codec8(self, data: bytes, known_imei: Optional[str]) -> Optional[NormalizedPosition]:
        if not known_imei: return None
        try:
            offset = 0
            timestamp_ms = struct.unpack('>Q', data[offset:offset+8])[0]
            device_time = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
            offset += 9
            lon = struct.unpack('>i', data[offset:offset+4])[0] / 10000000.0
            lat = struct.unpack('>i', data[offset+4:offset+8])[0] / 10000000.0
            alt = struct.unpack('>h', data[offset+8:offset+10])[0]
            angle = struct.unpack('>H', data[offset+10:offset+12])[0]
            sat = data[offset+12]
            speed = struct.unpack('>H', data[offset+13:offset+15])[0]
            offset += 15
            offset += 2 # IO Event + Total
            ignition = None; sensors = {}
            
            def parse_io(bw, func):
                nonlocal offset, ignition
                if offset + 1 > len(data): return
                cnt = data[offset]; offset += 1
                for _ in range(cnt):
                    if offset + 1 + bw > len(data): break
                    io_id = data[offset]
                    val = func(data[offset+1 : offset+1+bw])
                    if io_id == 239: ignition = bool(val)
                    if io_id in self.IO_MULTIPLIERS: val = round(float(val) * self.IO_MULTIPLIERS[io_id], 3)
                    key = self.IO_MAP.get(io_id, f"io_{io_id}")
                    sensors[key] = val
                    offset += 1 + bw
            
            parse_io(1, lambda b: b[0])
            parse_io(2, lambda b: struct.unpack('>H', b)[0])
            parse_io(4, lambda b: struct.unpack('>I', b)[0])
            parse_io(8, lambda b: struct.unpack('>Q', b)[0])

            return NormalizedPosition(imei=known_imei, device_time=device_time, latitude=lat, longitude=lon, altitude=float(alt), speed=float(speed), course=float(angle), satellites=sat, ignition=ignition, sensors=sensors, raw_data={"priority": data[8]})
        except Exception as e: return None

    async def encode_command(self, command_type: str, params: Dict[str, Any]) -> bytes: return b''
