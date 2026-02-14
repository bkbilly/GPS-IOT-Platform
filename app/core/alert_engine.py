"""
Alert Engine
Rule-based alerting with temporal logic and notifications
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
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.rule_cache = {} 
        self.alert_callback: Optional[Callable[[AlertHistory], Any]] = None 
        
    def set_alert_callback(self, callback: Callable):
        self.alert_callback = callback
    
    async def process_position_alerts(self, position, device, state):
        try:
            users = device.users
            if not users: return
            
            # Ensure alert_states is initialized
            if state.alert_states is None:
                state.alert_states = {}
            
            alerts = []
            
            # Checks for standard alerts
            speed_alert = await self._check_speeding(position, device, state)
            if speed_alert: alerts.append(speed_alert)
            
            idle_alert = await self._check_idling(position, device, state)
            if idle_alert: alerts.append(idle_alert)
            
            towing_alert = await self._check_towing(position, device, state)
            if towing_alert: alerts.append(towing_alert)
            
            geofence_alerts = await self._check_geofences(position, device, state)
            alerts.extend(geofence_alerts)
            
            maintenance_alert = await self._check_maintenance(device, state)
            if maintenance_alert: alerts.append(maintenance_alert)
            
            custom_alerts = await self._check_custom_rules(position, device, state)
            alerts.extend(custom_alerts)
            
            # Always update state if it was initialized
            if state.alert_states is not None:
                db = get_db()
                await db.update_device_alert_state(device.id, state.alert_states)

            # Dispatch collected alerts
            for alert_data in alerts:
                # Ensure coordinates are present
                if 'latitude' not in alert_data:
                    alert_data['latitude'] = position.latitude
                    alert_data['longitude'] = position.longitude
                
                await self._dispatch_alert(users, device, alert_data)
                
        except Exception as e:
            logger.error(f"Alert processing error: {e}")

    async def _dispatch_alert(self, users: List[User], device: Device, alert_data: Dict[str, Any]):
        """
        Handles database creation, real-time broadcasting, and external notifications.
        Ensures WebSocket broadcast only happens ONCE per alert event.
        """
        broadcasted = False
        
        for user in users:
            db = get_db()
            # 1. Create personal alert history record
            alert = await db.create_alert(AlertCreate(
                user_id=user.id, 
                device_id=device.id, 
                alert_type=alert_data['type'], 
                severity=alert_data['severity'], 
                message=alert_data['message'], 
                latitude=alert_data.get('latitude'), 
                longitude=alert_data.get('longitude'), 
                alert_metadata=alert_data.get('alert_metadata', {})
            ))
            
            # 2. Real-time broadcast (ONLY ONCE)
            if not broadcasted and self.alert_callback:
                await self.alert_callback(alert)
                broadcasted = True
                
            # 3. External notifications (Email, Telegram, etc. per user)
            await self._send_notification(user, device, alert_data)

    async def _check_towing(self, position, device, state):
        threshold = device.config.get('towing_threshold_meters')
        if threshold is None: return None
        if position.ignition:
            state.alert_states.pop('towing_anchor_lat', None)
            state.alert_states.pop('towing_anchor_lon', None)
            state.alert_states['towing_alerted'] = False
            return None
        anchor_lat = state.alert_states.get('towing_anchor_lat')
        anchor_lon = state.alert_states.get('towing_anchor_lon')
        if anchor_lat is None:
            state.alert_states['towing_anchor_lat'] = position.latitude
            state.alert_states['towing_anchor_lon'] = position.longitude
            return None
        db = get_db()
        async with db.get_session() as session:
            dist = await db._calculate_distance(session, anchor_lat, anchor_lon, position.latitude, position.longitude) * 1000 
        if dist > threshold:
            if not state.alert_states.get('towing_alerted'):
                state.alert_states['towing_alerted'] = True
                return {'type': AlertType.TOWING, 'severity': Severity.CRITICAL, 'message': f"Towing Alert: Vehicle moved {int(dist)}m while parked.", 'alert_metadata': {'config_key': 'towing_threshold_meters'}}
        return None

    async def _check_speeding(self, position, device, state):
        limit = device.config.get('speed_tolerance')
        # Allow custom duration, default to 30s
        duration_threshold = device.config.get('speed_duration_seconds', 30)
        
        # Reset tracking if below limit
        if limit is None or (position.speed or 0) <= limit:
            state.alert_states['speeding_since'] = None
            state.alert_states['speeding_alerted'] = False
            return None

        # Already alerted for this continuous speeding event
        if state.alert_states.get('speeding_alerted'):
            return None

        # Start tracking time when speed first crosses the limit
        since = state.alert_states.get('speeding_since')
        if not since:
            state.alert_states['speeding_since'] = position.device_time.isoformat()
            return None

        # Only alert if speeding for more than configured seconds
        start = datetime.fromisoformat(since).replace(tzinfo=None)
        duration_seconds = (position.device_time.replace(tzinfo=None) - start).total_seconds()
        
        if duration_seconds >= duration_threshold:
            state.alert_states['speeding_alerted'] = True
            return {
                'type': AlertType.SPEEDING, 
                'severity': Severity.WARNING, 
                'message': f"Speeding: {position.speed:.1f} km/h (Limit: {limit}).", 
                'alert_metadata': {'config_key': 'speed_tolerance'}
            }
        
        return None

    async def _check_idling(self, position, device, state):
        limit = device.config.get('idle_timeout_minutes')
        if limit is None or not position.ignition or (position.speed or 0) > 1.5:
            state.alert_states['idling_since'] = None; state.alert_states['idling_alerted'] = False; return None
        since = state.alert_states.get('idling_since')
        if not since: state.alert_states['idling_since'] = position.device_time.isoformat(); return None
        start = datetime.fromisoformat(since).replace(tzinfo=None)
        if (position.device_time.replace(tzinfo=None) - start).total_seconds() / 60 >= limit:
            if not state.alert_states.get('idling_alerted'):
                state.alert_states['idling_alerted'] = True
                return {'type': AlertType.IDLING, 'severity': Severity.INFO, 'message': f"Idle Alert: Vehicle idling for {limit} min.", 'alert_metadata': {'config_key': 'idle_timeout_minutes'}}
        return None

    async def _check_geofences(self, position, device, state):
        db = get_db(); violations = await db.check_geofence_violations(device.id, position.latitude, position.longitude)
        return [{'type': AlertType.GEOFENCE_ENTER if v['type'] == 'enter' else AlertType.GEOFENCE_EXIT, 'severity': Severity.WARNING, 'message': f"Geofence: {v['geofence_name']}", 'alert_metadata': {}} for v in violations]

    async def _check_maintenance(self, device, state):
        oil_km = device.config.get('maintenance', {}).get('oil_change_km')
        if oil_km:
            rem = oil_km - (state.total_odometer % oil_km)
            if 0 < rem <= 100 and not state.alert_states.get('maint_oil_alerted'):
                state.alert_states['maint_oil_alerted'] = True
                return {'type': AlertType.MAINTENANCE, 'severity': Severity.INFO, 'message': f"Maintenance: Oil due in {int(rem)} km."}
            elif rem > 100: state.alert_states['maint_oil_alerted'] = False
        return None

    async def _check_custom_rules(self, position, device, state):
        rules = device.config.get('custom_rules', [])
        alerts = []
        ctx = {'speed': position.speed or 0, 'ignition': position.ignition, **position.sensors}
        for rule_obj in rules:
            try:
                rule_str = rule_obj.get('rule') if isinstance(rule_obj, dict) else str(rule_obj)
                rule_name = rule_obj.get('name', 'Custom') if isinstance(rule_obj, dict) else "Custom"
                rule_ch = rule_obj.get('channels', []) if isinstance(rule_obj, dict) else []
                if not rule_str: continue
                if rule_str not in self.rule_cache: self.rule_cache[rule_str] = rule_engine.Rule(rule_str)
                if self.rule_cache[rule_str].matches(ctx):
                    key = f"c_f_{re.sub(r'[^a-zA-Z]', '', rule_str)}"
                    if not state.alert_states.get(key):
                        alerts.append({'type': AlertType.CUSTOM, 'severity': Severity.WARNING, 'message': f"Alert: {rule_name}", 'alert_metadata': {'selected_channels': rule_ch}})
                        state.alert_states[key] = True
                else: state.alert_states[f"c_f_{re.sub(r'[^a-zA-Z]', '', rule_str)}"] = False
            except: pass
        return alerts

    async def _send_notification(self, user: User, device: Device, alert_data: Dict[str, Any]):
        try:
            metadata = alert_data.get('alert_metadata', {})
            selected_names = None
            
            # 1. Determine which channel names are selected
            if 'selected_channels' in metadata:
                # Direct selection (usually from custom rules)
                selected_names = metadata['selected_channels']
            elif 'config_key' in metadata:
                # Keyed configuration (Speeding, Idling, etc)
                config_key = metadata['config_key']
                # Get selected channel names from device config
                # Default to None if key not found (which triggers fallback)
                # If key found but value is empty list, that means explicitly disabled
                alert_channels = device.config.get('alert_channels', {})
                if config_key in alert_channels:
                    selected_names = alert_channels[config_key]
                else:
                    selected_names = None # Not configured, use fallback

            user_ch = user.notification_channels or []
            urls = []

            # 2. Filter URLs based on names
            if selected_names is not None:
                # If names is a list (even empty), respect it strictly
                # This ensures an empty selection results in NO notifications
                urls = [c['url'] for c in user_ch if c['name'] in selected_names and c.get('url')]
            else:
                # Fallback: If no configuration exists for this alert type, 
                # send to all available user channels by default
                urls = [c['url'] for c in user_ch if c.get('url')]
            
            if urls:
                title = f"🚗 {device.name} - {alert_data['type'].value.upper()}"
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(self.executor, self._send_apprise_notification, urls, title, alert_data['message'])
        except Exception as e: 
            logger.error(f"Notify error: {e}")
    
    def _send_apprise_notification(self, urls, title, body):
        try:
            apobj = Apprise()
            for url in urls: apobj.add(url)
            apobj.notify(title=title, body=body)
        except: pass

async def offline_detection_task():
    while True:
        try:
            db = get_db(); offline = await db.get_offline_devices()
            for device, state in offline:
                await db.mark_device_offline(device.id)
                timeout = device.config.get('offline_timeout_hours', 24)
                if not state.alert_states.get('offline_alerted'):
                    state.alert_states['offline_alerted'] = True
                    
                    alert_data = {
                        'type': AlertType.OFFLINE, 
                        'severity': Severity.WARNING, 
                        'message': f"Device {device.name} offline (> {timeout}h).", 
                        'alert_metadata': {'config_key': 'offline_timeout_hours'}
                    }
                    
                    # Use central dispatcher to avoid double WS broadcast
                    await alert_engine._dispatch_alert(device.users, device, alert_data)
            
            await asyncio.sleep(300)
        except: await asyncio.sleep(60)

alert_engine = AlertEngine()
def get_alert_engine() -> AlertEngine: return alert_engine