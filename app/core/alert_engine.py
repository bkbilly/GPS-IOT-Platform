"""
Alert Engine
Rule-based alerting with temporal logic and hysteresis
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable
import logging
from concurrent.futures import ThreadPoolExecutor
import re

import rule_engine
from apprise import Apprise

from models import Device, DeviceState, User, AlertHistory
from models.schemas import AlertCreate, AlertType, Severity, NormalizedPosition
from core.database import get_db

logger = logging.getLogger(__name__)


class AlertEngine:
    """
    Alert engine with temporal logic and hysteresis
    Prevents alert spam by tracking alert states
    """
    
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.rule_cache = {} 
        self.alert_callback: Optional[Callable[[AlertHistory], Any]] = None 
        
    def set_alert_callback(self, callback: Callable):
        """Set callback to be called when an alert is created"""
        self.alert_callback = callback
    
    async def process_position_alerts(
        self,
        position: NormalizedPosition,
        device: Device,
        state: DeviceState
    ):
        """Process all alert rules for a new position"""
        try:
            users = device.users
            if not users: return
            
            alerts = []
            
            # 1. Speeding
            speed_alert = await self._check_speeding(position, device, state)
            if speed_alert: alerts.append(speed_alert)
            
            # 2. Idling
            idle_alert = await self._check_idling(position, device, state)
            if idle_alert: alerts.append(idle_alert)
            
            # 3. Towing (Virtual Geofence)
            towing_alert = await self._check_towing(position, device, state)
            if towing_alert: alerts.append(towing_alert)
            
            # 4. Geofence
            geofence_alerts = await self._check_geofences(position, device, state)
            alerts.extend(geofence_alerts)
            
            # 5. Maintenance
            maintenance_alert = await self._check_maintenance(device, state)
            if maintenance_alert: alerts.append(maintenance_alert)
            
            # 6. Custom Rules
            custom_alerts = await self._check_custom_rules(position, device, state)
            alerts.extend(custom_alerts)
            
            # Persist state changes
            if state.alert_states:
                db = get_db()
                await db.update_device_alert_state(device.id, state.alert_states)

            # Send alerts
            for alert_data in alerts:
                if 'latitude' not in alert_data:
                    alert_data['latitude'] = position.latitude
                    alert_data['longitude'] = position.longitude
                for user in users:
                    await self._send_alert(user, device, alert_data)
        
        except Exception as e:
            logger.error(f"Alert processing error: {e}", exc_info=True)

    async def _check_towing(
        self,
        position: NormalizedPosition,
        device: Device,
        state: DeviceState
    ) -> Optional[Dict[str, Any]]:
        threshold = device.config.get('towing_threshold_meters')
        if threshold is None: return None

        if position.ignition:
            state.alert_states.pop('towing_anchor_lat', None)
            state.alert_states.pop('towing_anchor_lon', None)
            state.alert_states['towing_alerted'] = False
            return None
        
        anchor_lat = state.alert_states.get('towing_anchor_lat')
        anchor_lon = state.alert_states.get('towing_anchor_lon')

        if anchor_lat is None or anchor_lon is None:
            state.alert_states['towing_anchor_lat'] = position.latitude
            state.alert_states['towing_anchor_lon'] = position.longitude
            return None

        db = get_db()
        async with db.get_session() as session:
            distance_from_anchor = await db._calculate_distance(
                session, anchor_lat, anchor_lon,
                position.latitude, position.longitude
            ) * 1000 
        
        if distance_from_anchor > threshold:
            if not state.alert_states.get('towing_alerted'):
                state.alert_states['towing_alerted'] = True
                return {
                    'type': AlertType.TOWING,
                    'severity': Severity.CRITICAL,
                    'message': (f"Towing Alert! Vehicle moved {int(distance_from_anchor)}m "
                                f"away from its parked position (Limit: {threshold}m)."),
                    'alert_metadata': {
                        'distance_meters': int(distance_from_anchor),
                        'threshold': threshold,
                        'config_key': 'towing_threshold_meters' # For channel filtering
                    }
                }
        return None

    async def _check_speeding(self, position, device, state) -> Optional[Dict[str, Any]]:
        if position.speed is None: return None
        limit = device.config.get('speed_tolerance')
        if limit is None: return None
        
        if position.speed <= limit:
            state.alert_states['speeding_since'] = None
            state.alert_states['speeding_alerted'] = False
            return None
        
        since = state.alert_states.get('speeding_since')
        if not since:
            state.alert_states['speeding_since'] = position.device_time.isoformat()
            return None
        
        start = datetime.fromisoformat(since).replace(tzinfo=None)
        cur = position.device_time.replace(tzinfo=None)
        duration = (cur - start).total_seconds()
        
        if duration >= 30:
             if not state.alert_states.get('speeding_alerted'):
                state.alert_states['speeding_alerted'] = True
                return {
                    'type': AlertType.SPEEDING,
                    'severity': Severity.WARNING,
                    'message': f"Speeding detected: {position.speed:.1f} km/h (Limit: {limit} km/h) for {int(duration)}s.",
                    'alert_metadata': {'speed': position.speed, 'limit': limit, 'duration': duration, 'config_key': 'speed_tolerance'}
                }
        return None
    
    async def _check_idling(self, position, device, state) -> Optional[Dict[str, Any]]:
        limit_min = device.config.get('idle_timeout_minutes')
        if limit_min is None: return None

        if not position.ignition or (position.speed or 0) > 1.5:
            state.alert_states['idling_since'] = None
            state.alert_states['idling_alerted'] = False
            return None
        
        since = state.alert_states.get('idling_since')
        if not since:
            state.alert_states['idling_since'] = position.device_time.isoformat()
            return None
        
        start = datetime.fromisoformat(since).replace(tzinfo=None)
        cur = position.device_time.replace(tzinfo=None)
        duration_min = (cur - start).total_seconds() / 60
        
        if duration_min >= limit_min:
            if not state.alert_states.get('idling_alerted'):
                state.alert_states['idling_alerted'] = True
                return {
                    'type': AlertType.IDLING,
                    'severity': Severity.INFO,
                    'message': f"Idling Alert: Vehicle has been stationary with ignition ON for {int(duration_min)} minutes.",
                    'alert_metadata': {'duration_minutes': int(duration_min), 'config_key': 'idle_timeout_minutes'}
                }
        return None
    
    async def _check_geofences(self, position, device, state) -> List[Dict[str, Any]]:
        db = get_db()
        violations = await db.check_geofence_violations(device.id, position.latitude, position.longitude)
        alerts = []
        for v in violations:
            action = "Entered" if v['type'] == 'enter' else "Exited"
            alerts.append({
                'type': AlertType.GEOFENCE_ENTER if v['type'] == 'enter' else AlertType.GEOFENCE_EXIT,
                'severity': Severity.WARNING,
                'message': f"Geofence Alert: Vehicle {action} zone '{v['geofence_name']}' at {position.device_time.strftime('%H:%M')}.",
                'alert_metadata': {'geofence_name': v['geofence_name']} # Standard geofences currently use all channels
            })
        return alerts
    
    async def _check_maintenance(self, device, state) -> Optional[Dict[str, Any]]:
        maint = device.config.get('maintenance', {})
        oil_km = maint.get('oil_change_km')
        if oil_km:
            rem = oil_km - (state.total_odometer % oil_km)
            if 0 < rem <= 100:
                 if not state.alert_states.get('maint_oil_alerted'):
                    state.alert_states['maint_oil_alerted'] = True
                    return {
                        'type': AlertType.MAINTENANCE,
                        'severity': Severity.INFO,
                        'message': f"Maintenance Reminder: Oil change due in {int(rem)} km.",
                        'alert_metadata': {'km_remaining': int(rem)}
                    }
            else:
                state.alert_states['maint_oil_alerted'] = False
        return None
    
    async def _check_custom_rules(self, position, device, state) -> List[Dict[str, Any]]:
        rules = device.config.get('custom_rules', [])
        alerts = []
        ctx = {'speed': position.speed or 0, 'ignition': position.ignition, **position.sensors}

        for rule_obj in rules:
            try:
                rule_str = rule_obj.get('rule') if isinstance(rule_obj, dict) else str(rule_obj)
                rule_name = rule_obj.get('name', 'Custom Alert') if isinstance(rule_obj, dict) else "Custom Alert"
                rule_channels = rule_obj.get('channels', []) if isinstance(rule_obj, dict) else []
                
                if not rule_str: continue

                match = re.match(r"(.*) for (\d+) (second|minute|hour)s?", rule_str, re.IGNORECASE)
                cond_str = match.group(1).strip() if match else rule_str
                dur_sec = 0
                if match:
                    amt = int(match.group(2))
                    unit = match.group(3).lower()
                    dur_sec = amt if unit == 'second' else amt * 60 if unit == 'minute' else amt * 3600

                if cond_str not in self.rule_cache: self.rule_cache[cond_str] = rule_engine.Rule(cond_str)
                rule = self.rule_cache[cond_str]
                
                safe_key = re.sub(r'[^a-zA-Z0-9]', '_', rule_str)
                start_key, fired_key = f"c_s_{safe_key}", f"c_f_{safe_key}"
                
                if rule.matches(ctx):
                    if dur_sec > 0:
                        iso = state.alert_states.get(start_key)
                        if not iso:
                            state.alert_states[start_key] = position.device_time.isoformat()
                        else:
                            start = datetime.fromisoformat(iso).replace(tzinfo=None)
                            if (position.device_time.replace(tzinfo=None) - start).total_seconds() >= dur_sec:
                                if not state.alert_states.get(fired_key):
                                    alerts.append({
                                        'type': AlertType.CUSTOM, 'severity': Severity.WARNING,
                                        'message': f"Custom Alert '{rule_name}' triggered.",
                                        'alert_metadata': {'name': rule_name, 'rule': rule_str, 'selected_channels': rule_channels}
                                    })
                                    state.alert_states[fired_key] = True
                    elif not state.alert_states.get(fired_key):
                        alerts.append({
                            'type': AlertType.CUSTOM, 'severity': Severity.WARNING,
                            'message': f"Custom Alert '{rule_name}' triggered.",
                            'alert_metadata': {'name': rule_name, 'rule': rule_str, 'selected_channels': rule_channels}
                        })
                        state.alert_states[fired_key] = True
                else:
                    state.alert_states.pop(start_key, None)
                    state.alert_states.pop(fired_key, None)
            except: pass
        return alerts

    async def _send_alert(self, user: User, device: Device, alert_data: Dict[str, Any]):
        db = get_db()
        alert = await db.create_alert(AlertCreate(
            user_id=user.id, device_id=device.id,
            alert_type=alert_data['type'], severity=alert_data['severity'],
            message=alert_data['message'], latitude=alert_data.get('latitude'),
            longitude=alert_data.get('longitude'), address=alert_data.get('address'),
            alert_metadata=alert_data.get('alert_metadata', {})
        ))
        if self.alert_callback: await self.alert_callback(alert)
        await self._send_notification(user, device, alert_data)
    
    async def _send_notification(self, user: User, device: Device, alert_data: Dict[str, Any]):
        try:
            # Determine which channels to use
            selected_names = []
            
            # 1. Check if it's a custom rule with specific channels
            metadata = alert_data.get('alert_metadata', {})
            if 'selected_channels' in metadata:
                selected_names = metadata['selected_channels']
            
            # 2. Check standard alert type configuration
            elif 'config_key' in metadata:
                config_key = metadata['config_key']
                selected_names = device.config.get('alert_channels', {}).get(config_key, [])
            
            # 3. Fallback: If no specific names selected, use ALL channels for compatibility
            user_channels = user.notification_channels or []
            
            if selected_names:
                urls = [c['url'] for c in user_channels if c['name'] in selected_names and c.get('url')]
            else:
                urls = [c['url'] for c in user_channels if c.get('url')]
            
            if not urls: return
            
            title = f"🚗 {device.name} - {alert_data['type'].value.upper()}"
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self.executor, self._send_apprise_notification, urls, title, alert_data['message'])
        except Exception as e:
            logger.error(f"Notification error: {e}")
    
    def _send_apprise_notification(self, urls, title, body):
        try:
            apobj = Apprise()
            for url in urls: apobj.add(url)
            apobj.notify(title=title, body=body)
        except: pass

async def offline_detection_task():
    while True:
        try:
            db = get_db()
            offline = await db.get_offline_devices()
            for device, state in offline:
                await db.mark_device_offline(device.id)
                timeout = device.config.get('offline_timeout_hours', 24)
                if not state.alert_states.get('offline_alerted'):
                    state.alert_states['offline_alerted'] = True
                    
                    # Filter offline alert channels
                    selected_names = device.config.get('alert_channels', {}).get('offline_timeout_hours', [])
                    
                    for user in device.users:
                        alert = await db.create_alert(AlertCreate(
                            user_id=user.id, device_id=device.id, alert_type=AlertType.OFFLINE,
                            severity=Severity.WARNING, message=f"Device {device.name} is offline (> {timeout}h).",
                            alert_metadata={'last_update': state.last_update.isoformat(), 'config_key': 'offline_timeout_hours'}
                        ))
                        if alert_engine.alert_callback: await alert_engine.alert_callback(alert)
            await asyncio.sleep(300)
        except: await asyncio.sleep(60)

alert_engine = AlertEngine()
def get_alert_engine() -> AlertEngine: return alert_engine