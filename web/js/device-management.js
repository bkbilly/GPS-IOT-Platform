let devices = [];
let userChannels = [];
let editingDeviceId = null;
let activeAlerts = new Set();
let customRules = [];

// Raw Data State
let rawData = [];
let currentPage = 1;
const itemsPerPage = 50;
let currentRawDeviceId = null;

const VEHICLE_ICONS = {
    car: '🚗',
    truck: '🚛',
    van: '🚐',
    motorcycle: '🏍️',
    bus: '🚌',
    person: '🚶',
    airplane: '✈️',
    bicycle: '🚲',
    boat: '🚢',
    scooter: '🛴',
    tractor: '🚜',
    arrow: '▲',
    other: '📦'
};

const ALERT_TYPES = {
    speed_tolerance: { 
        label: 'Speed Limit Alert', 
        desc: 'Alert when speed exceeds this limit (verified after 30s of continuous speeding).',
        unit: 'km/h', 
        min: 0, max: 300, 
        default: 100,
        type: 'number'
    },
    idle_timeout_minutes: { 
        label: 'Idle Timeout Alert', 
        desc: 'Alert when vehicle idles (ignition on, speed 0) longer than this duration.',
        unit: 'minutes', 
        min: 1, max: 120, 
        default: 10,
        type: 'number'
    },
    offline_timeout_hours: { 
        label: 'Offline Timeout Alert', 
        desc: 'Alert when device stops sending data for this duration.',
        unit: 'hours', 
        min: 1, max: 168, 
        default: 24,
        type: 'number'
    },
    towing_threshold_meters: {
        label: 'Towing Alert',
        desc: 'Alert when vehicle moves more than this distance from where ignition was turned OFF.',
        unit: 'meters',
        min: 10, max: 1000,
        default: 100,
        type: 'number'
    }
};

const DEFAULT_PROTOCOL = 'teltonika';
const DEFAULT_TYPE = 'car';

// ADDED: Auth Check
function checkLogin() {
    if (!localStorage.getItem('auth_token')) {
        window.location.href = 'login.html';
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    checkLogin();
    await loadUserChannels();
    await loadDevices();
});

async function loadUserChannels() {
    try {
        const userId = localStorage.getItem('user_id') || 1;
        const res = await fetch(`${API_BASE}/users/${userId}`);
        if (!res.ok) throw new Error('Failed to load user channels');
        const user = await res.json();
        userChannels = user.notification_channels || [];
    } catch (e) { console.error("Error loading channels", e); }
}

async function loadDevices() {
    try {
        const userId = localStorage.getItem('user_id') || 1;
        const res = await fetch(`${API_BASE}/devices?user_id=${userId}&_t=${Date.now()}`);
        if (!res.ok) throw new Error('Failed to load devices');
        devices = await res.json();
        renderDevices();
    } catch (e) { showAlert('Error loading devices', 'error'); }
}

function renderDevices() {
    const grid = document.getElementById('devicesGrid');
    
    if (devices.length === 0) {
        grid.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; padding: 4rem; color: var(--text-muted);">
                <div style="font-size: 3rem; margin-bottom: 1rem;">📡</div>
                <h3 style="margin-bottom: 0.5rem;">No devices yet</h3>
                <p>Click "Add New Device" to register your first GPS tracker</p>
            </div>
        `;
        return;
    }
    
    grid.innerHTML = devices.map(d => {
        const vehicleIcon = VEHICLE_ICONS[d.vehicle_type] || '📡';
        return `
        <div class="device-card">
            <div class="device-card-header">
                <div>
                    <div class="device-name">${vehicleIcon} ${d.name}</div>
                    <div class="device-imei">${d.imei}</div>
                </div>
                <div class="device-status ${d.is_active ? 'active' : 'inactive'}">
                    ${d.is_active ? 'Active' : 'Inactive'}
                </div>
            </div>
            
            <div class="device-details">
                <div class="detail-row">
                    <span class="detail-label">Protocol</span>
                    <span class="detail-value">${d.protocol}</span>
                </div>
                ${d.vehicle_type ? `
                <div class="detail-row">
                    <span class="detail-label">Vehicle Type</span>
                    <span class="detail-value">${d.vehicle_type}</span>
                </div>
                ` : ''}
                ${d.license_plate ? `
                <div class="detail-row">
                    <span class="detail-label">License Plate</span>
                    <span class="detail-value">${d.license_plate}</span>
                </div>
                ` : ''}
                <div class="detail-row">
                    <span class="detail-label">Created</span>
                    <span class="detail-value">${new Date(d.created_at).toLocaleDateString()}</span>
                </div>
            </div>
            
            <div class="device-actions">
                <button class="btn btn-secondary" onclick="editDevice(${d.id})" style="flex: 1;">
                    ✏️ Edit
                </button>
                <button class="btn btn-secondary" onclick="openRawDataModal(${d.id})" style="flex: 1;">
                    📋 Raw Data
                </button>
                <button class="btn btn-danger" onclick="deleteDevice(${d.id})" style="flex: 1;">
                    🗑️ Delete
                </button>
            </div>
        </div>
    `}).join('');
}

function openAddDeviceModal() {
    editingDeviceId = null;
    document.getElementById('modalTitle').textContent = 'Add New Device';
    document.getElementById('submitText').textContent = 'Add Device';
    document.getElementById('deviceForm').reset();
    
    // Default Alerts
    renderAlertConfiguration({
        custom_rules: []
    });
    
    document.getElementById('deviceModal').classList.add('active');
}

function editDevice(deviceId) {
    // Note: Use '==' to match string ID from HTML with number ID from object if necessary
    const d = devices.find(x => x.id == deviceId);
    if (!d) return;
    
    editingDeviceId = d.id;
    document.getElementById('modalTitle').textContent = 'Edit Device';
    document.getElementById('submitText').textContent = 'Save Changes';
    
    // Populate form
    document.getElementById('deviceName').value = d.name;
    document.getElementById('deviceImei').value = d.imei;
    // Protocol and Vehicle Type are hidden but handled in submit
    document.getElementById('vehicleType').value = d.vehicle_type || '';
    document.getElementById('licensePlate').value = d.license_plate || '';
    document.getElementById('vin').value = d.vin || '';
    
    // Config fields
    const config = d.config || {};
    document.getElementById('oilChangeKm').value = config.maintenance?.oil_change_km || 10000;
    document.getElementById('tireRotationKm').value = config.maintenance?.tire_rotation_km || 8000;
    
    // Alert Config
    renderAlertConfiguration(config);
    
    document.getElementById('deviceModal').classList.add('active');
}

// ================= Alert Logic =================

function renderAlertConfiguration(config) {
    const list = document.getElementById('activeAlertsList');
    list.innerHTML = '';
    activeAlerts.clear();

    const channelsConfig = config.alert_channels || {};

    for (const [key, def] of Object.entries(ALERT_TYPES)) {
        if (config[key] !== undefined && config[key] !== null) {
            addAlertRow(key, config[key], channelsConfig[key] || []);
        }
    }
    updateAddAlertDropdown();

    // Custom Rules
    customRules = (config.custom_rules || []).map(r => {
        if (typeof r === 'string') return { name: 'Custom Alert', rule: r, channels: [] };
        return r;
    });
    renderCustomRules();
}

function addAlertRow(key, value, selectedChannels = []) {
    const def = ALERT_TYPES[key];
    activeAlerts.add(key);

    const div = document.createElement('div');
    div.className = 'alert-config-item';
    div.id = `alert-row-${key}`;

    // Create channel pills
    const channelHtml = userChannels.map(c => `
        <div class="channel-pill ${selectedChannels.includes(c.name) ? 'active' : ''}" 
             onclick="this.classList.toggle('active')" data-name="${c.name}">
            ${c.name}
        </div>
    `).join('');

    div.innerHTML = `
        <div class="alert-config-item-top">
            <div>
                <div class="alert-config-label">${def.label}</div>
                <div class="alert-config-desc">${def.desc}</div>
            </div>
            <button type="button" class="btn btn-danger" style="padding: 0.3rem 0.6rem;" onclick="removeAlertRow('${key}')">✕</button>
        </div>
        <div style="display:flex; align-items:center; gap:0.5rem;">
            <input type="number" 
                   class="form-input alert-config-input" 
                   data-key="${key}"
                   value="${value}" 
                   min="${def.min}" 
                   max="${def.max}">
            <span style="color: var(--text-muted); font-size: 0.875rem;">${def.unit}</span>
        </div>
        <div class="form-label" style="font-size:0.7rem; margin-top:1rem; margin-bottom:0.2rem">Notify via:</div>
        <div class="channel-selector" id="channels-${key}">${channelHtml}</div>
    `;
    
    document.getElementById('activeAlertsList').appendChild(div);
    updateAddAlertDropdown();
}

function removeAlertRow(key) {
    document.getElementById(`alert-row-${key}`).remove();
    activeAlerts.delete(key);
    updateAddAlertDropdown();
}

function updateAddAlertDropdown() {
    const select = document.getElementById('addAlertSelect');
    select.innerHTML = '<option value="">+ Add alert type...</option>';
    
    let count = 0;
    for (const [key, def] of Object.entries(ALERT_TYPES)) {
        if (!activeAlerts.has(key)) {
            const option = document.createElement('option');
            option.value = key;
            option.textContent = def.label;
            select.appendChild(option);
            count++;
        }
    }
    
    document.querySelector('.alert-add-container').style.display = count > 0 ? 'flex' : 'none';
}

function addSelectedAlert() {
    const select = document.getElementById('addAlertSelect');
    const key = select.value;
    if (key) {
        addAlertRow(key, ALERT_TYPES[key].default);
    }
}

// Custom Rules Logic
function renderCustomRules() {
    const container = document.getElementById('customRulesList');
    container.innerHTML = '';
    
    customRules.forEach((ruleObj, index) => {
        const div = document.createElement('div');
        div.className = 'alert-config-item';
        
        const channelHtml = userChannels.map(c => `
            <div class="channel-pill ${(ruleObj.channels || []).includes(c.name) ? 'active' : ''}" 
                 onclick="toggleCustomRuleChannel(${index}, '${c.name}', this)">
                ${c.name}
            </div>
        `).join('');

        div.innerHTML = `
            <div class="alert-config-item-top">
                <div>
                    <div class="alert-config-label">${ruleObj.name}</div>
                    <div class="alert-config-desc">${ruleObj.rule}</div>
                </div>
                <button type="button" class="btn btn-danger" style="padding: 0.3rem 0.6rem;" onclick="removeCustomRule(${index})">✕</button>
            </div>
            <div class="channel-selector">${channelHtml}</div>
        `;
        container.appendChild(div);
    });
}

function toggleCustomRuleChannel(ruleIndex, channelName, element) {
    element.classList.toggle('active');
    if (!customRules[ruleIndex].channels) customRules[ruleIndex].channels = [];
    
    const idx = customRules[ruleIndex].channels.indexOf(channelName);
    if (idx > -1) {
        customRules[ruleIndex].channels.splice(idx, 1);
    } else {
        customRules[ruleIndex].channels.push(channelName);
    }
}

function addCustomRule() {
    const nameInput = document.getElementById('newRuleName');
    const ruleInput = document.getElementById('newRuleCond');
    
    const name = nameInput.value.trim();
    const rule = ruleInput.value.trim();
    
    if (name && rule) {
        customRules.push({ name: name, rule: rule, channels: [] });
        nameInput.value = '';
        ruleInput.value = '';
        renderCustomRules();
    }
}

function removeCustomRule(index) {
    customRules.splice(index, 1);
    renderCustomRules();
}

// ================= Raw Data Logic =================

async function openRawDataModal(deviceId) {
    currentRawDeviceId = deviceId;
    currentPage = 1;
    
    document.getElementById('rawDataModal').classList.add('active');
    document.getElementById('rawDataBody').innerHTML = '<tr><td colspan="9" style="text-align:center;">Loading...</td></tr>';
    
    // Fetch data (Last 24 hours, Descending)
    const endTime = new Date();
    const startTime = new Date(endTime - 24 * 60 * 60 * 1000); 
    
    try {
        const response = await fetch(`${API_BASE}/positions/history`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                device_id: deviceId,
                start_time: startTime.toISOString(),
                end_time: endTime.toISOString(),
                max_points: 1000,
                order: 'desc'
            })
        });

        if (!response.ok) {
            throw new Error(`Server error: ${response.status}`);
        }

        const data = await response.json();
        rawData = data.features || [];
        renderRawDataPage();
    } catch (error) {
        console.error("Fetch history error:", error);
        document.getElementById('rawDataBody').innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--accent-danger);">Failed to load data</td></tr>`;
    }
}

function closeRawDataModal() {
    document.getElementById('rawDataModal').classList.remove('active');
}

function changeRawDataPage(delta) {
    const maxPage = Math.ceil(rawData.length / itemsPerPage) || 1;
    const newPage = currentPage + delta;
    
    if (newPage >= 1 && newPage <= maxPage) {
        currentPage = newPage;
        renderRawDataPage();
    }
}

function renderRawDataPage() {
    const startIdx = (currentPage - 1) * itemsPerPage;
    const endIdx = startIdx + itemsPerPage;
    const pageItems = rawData.slice(startIdx, endIdx);
    
    const tbody = document.getElementById('rawDataBody');
    tbody.innerHTML = '';
    
    if (pageItems.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;">No data available</td></tr>';
        return;
    }
    
    pageItems.forEach(item => {
        const p = item.properties || {};
        const geom = item.geometry || {};
        const coords = geom.coordinates || [0, 0];
        
        const sensors = p.sensors || {};
        // Simple stringify for attributes column
        const attributesStr = JSON.stringify(sensors).substring(0, 100) + (JSON.stringify(sensors).length > 100 ? '...' : '');

        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${p.time ? new Date(p.time).toLocaleString() : 'N/A'}</td>
            <td>${coords[1].toFixed(5)}</td>
            <td>${coords[0].toFixed(5)}</td>
            <td>${(p.speed || 0).toFixed(1)} km/h</td>
            <td>${(p.course || 0).toFixed(0)}°</td>
            <td>${p.satellites || 0}</td>
            <td>${(p.altitude || 0).toFixed(0)} m</td>
            <td>${p.ignition ? 'ON' : 'OFF'}</td>
            <td style="max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: var(--font-mono); font-size: 0.75rem;" title="${JSON.stringify(sensors)}">
                ${attributesStr}
            </td>
        `;
        tbody.appendChild(row);
    });
    
    const maxPage = Math.ceil(rawData.length / itemsPerPage) || 1;
    document.getElementById('pageInfo').textContent = `Page ${currentPage} of ${maxPage}`;
    document.getElementById('prevPageBtn').disabled = currentPage === 1;
    document.getElementById('nextPageBtn').disabled = currentPage === maxPage;
}

// ===============================================

function closeDeviceModal() {
    document.getElementById('deviceModal').classList.remove('active');
}

async function handleSubmit(event) {
    event.preventDefault();
    
    const submitBtn = document.getElementById('submitBtn');
    const submitText = document.getElementById('submitText');
    const submitLoading = document.getElementById('submitLoading');
    
    submitBtn.disabled = true;
    submitText.style.display = 'none';
    submitLoading.style.display = 'inline-block';
    
    // Build Alert Config
    const configAlerts = {};
    const alertChannels = {};
    
    // Iterate over active alerts in UI list
    document.querySelectorAll('#activeAlertsList .alert-config-item').forEach(item => {
        const input = item.querySelector('.alert-config-input');
        const key = input.dataset.key;
        const val = parseFloat(input.value);
        
        if (!isNaN(val)) {
            configAlerts[key] = val;
            
            // Gather selected channels
            const selected = [];
            item.querySelectorAll('.channel-pill.active').forEach(pill => {
                selected.push(pill.dataset.name);
            });
            alertChannels[key] = selected;
        }
    });

    let currentConfig = {};
    let protocol = DEFAULT_PROTOCOL;
    let vehicleType = DEFAULT_TYPE;
    
    if (editingDeviceId) {
        const device = devices.find(d => d.id === editingDeviceId);
        if (device) {
            currentConfig = device.config || {};
            protocol = device.protocol;
            vehicleType = device.vehicle_type;
        }
    }

    const deviceData = {
        name: document.getElementById('deviceName').value,
        imei: document.getElementById('deviceImei').value,
        protocol: protocol,
        vehicle_type: document.getElementById('vehicleType').value || vehicleType,
        license_plate: document.getElementById('licensePlate').value || null,
        vin: document.getElementById('vin').value || null,
        config: {
            // Only include alerts that are currently in the UI
            ...configAlerts,
            // Preserve non-alert config from existing device
            speed_duration_seconds: currentConfig.speed_duration_seconds || 30,
            sensors: currentConfig.sensors || {},
            // Set alert channels and rules
            alert_channels: alertChannels,
            custom_rules: customRules,
            maintenance: {
                oil_change_km: parseInt(document.getElementById('oilChangeKm').value) || 10000,
                tire_rotation_km: parseInt(document.getElementById('tireRotationKm').value) || 8000
            }
        }
    };
    
    try {
        let response;
        if (editingDeviceId) {
            response = await fetch(`${API_BASE}/devices/${editingDeviceId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(deviceData)
            });
        } else {
            response = await fetch(`${API_BASE}/devices`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(deviceData)
            });
        }
        
        if (response.ok) {
            showAlert(editingDeviceId ? 'Device updated' : 'Device added', 'success');
            closeDeviceModal();
            await loadDevices();
        } else {
            const error = await response.json();
            showAlert(error.detail || 'Failed to save', 'error');
        }
    } catch (error) {
        showAlert('Failed to save device', 'error');
    } finally {
        submitBtn.disabled = false;
        submitText.style.display = 'inline';
        submitLoading.style.display = 'none';
    }
}

async function deleteDevice(deviceId) {
    if (!confirm('Are you sure you want to delete this device?')) return;
    
    try {
        const response = await fetch(`${API_BASE}/devices/${deviceId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showAlert('Device deleted', 'success');
            await loadDevices();
        } else {
            showAlert('Failed to delete', 'error');
        }
    } catch (error) {
        showAlert('Failed to delete', 'error');
    }
}

function showAlert(message, type) {
    const container = document.getElementById('alertContainer');
    const alert = document.createElement('div');
    alert.className = `alert alert-${type}`;
    alert.innerHTML = `<span>${type === 'success' ? '✓' : '✕'}</span><span>${message}</span>`;
    
    container.appendChild(alert);
    
    setTimeout(() => {
        alert.classList.add('alert-hidden');
        setTimeout(() => alert.remove(), 300);
    }, 3000);
}