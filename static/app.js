const statusBadge = document.getElementById("statusBadge");
const entityTable = document.getElementById("entityTable");
const detailsOutput = document.getElementById("detailsOutput");
const eventLog = document.getElementById("eventLog");
const selectedHandleField = document.getElementById("selectedHandle");

function log(message) {
    const time = new Date().toLocaleTimeString();
    eventLog.textContent += `[${time}] ${message}\n`;
    eventLog.scrollTop = eventLog.scrollHeight;
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function fetchJson(endpoint, options = {}) {
    const API_BASE = "http://127.0.0.1:8000";
    const url = `${API_BASE}${endpoint}`;
    
    console.log("========== API REQUEST ==========");
    console.log("Endpoint:", endpoint);
    console.log("Full URL:", url);
    console.log("Method:", options.method || "GET");
    if (options.body) {
        try {
            console.log("Body:", JSON.parse(options.body));
        } catch {
            console.log("Body:", options.body);
        }
    }
    
    try {
        const response = await fetch(url, options);
        console.log("Response Status:", response.status);
        
        if (!response.ok) {
            const errorText = await response.text();
            console.error("API ERROR Response:");
            console.error(errorText);
            throw new Error(`Request failed (${response.status}): ${errorText}`);
        }
        
        const data = await response.json();
        console.log("========== API RESPONSE ==========");
        console.log(data);
        return data;
    } catch (err) {
        console.error("========== FETCH FAILED ==========");
        console.error("Error:", err.message);
        throw err;
    }
}

async function connect() {
    try {
        console.log("Initiating AutoCAD connection...");
        const data = await fetchJson('/connect', {
            method: "POST"
        });
        console.log("Connection successful:", data);
        const documentName = data?.status?.document || 'AutoCAD';
        statusBadge.textContent = `Connected: ${documentName}`;
        statusBadge.style.color = "limegreen";
        log(`Connected to AutoCAD document '${documentName}'.`);
        await loadEntities();
    } catch (err) {
        console.error("Connection error:", err);
        statusBadge.textContent = "Disconnected";
        statusBadge.style.color = "crimson";
        log(`Connect failed: ${err.message}`);
    }
}

async function loadEntities() {
    try {
        console.log("========== ENTITY REFRESH ==========");
        const startTime = Date.now();
        const entities = await fetchJson('/entities');
        const loadTime = Date.now() - startTime;
        renderEntityRows(entities);
        log(`Loaded ${entities.length} entities (${loadTime}ms).`);
    } catch (err) {
        log('Load entities failed: ' + err.message);
    }
}

async function refreshEntities() {
    try {
        console.log("========== ENTITY REFRESH ==========");
        const startTime = Date.now();
        log('Refreshing entity list from AutoCAD...');
        const entities = await fetchJson('/refresh');
        const refreshTime = Date.now() - startTime;
        renderEntityRows(entities);
        log(`Refreshed ${entities.length} entities (${refreshTime}ms).`);
    } catch (err) {
        log('Refresh failed: ' + err.message);
    }
}

function renderEntityRows(entities) {
    entityTable.innerHTML = '';
    entities.forEach(item => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${item.handle}</td>
            <td>${item.entity_type}</td>
            <td>${item.block_name || ''}</td>
            <td>${item.layer || ''}</td>
            <td>${item.insertion_point ? item.insertion_point.join(', ') : ''}</td>
            <td>${item.rotation ?? ''}</td>
        `;
        row.addEventListener('click', () => {
            console.log("========== ENTITY SELECTED ==========");
            console.log("Handle:", item.handle);
            console.log("Type:", item.entity_type);
            console.log("Details:", item);
            selectedHandleField.value = item.handle;
            detailsOutput.textContent = JSON.stringify(item, null, 2);
            setPipeHandlesFromSelection(item.handle);
        });
        entityTable.appendChild(row);
    });
}

function setPipeHandlesFromSelection(handle) {
    const startInput = document.getElementById('startHandle');
    const endInput = document.getElementById('endHandle');
    const currentStart = startInput.value.trim();
    const currentEnd = endInput.value.trim();

    if (!currentStart || (currentStart && currentEnd)) {
        startInput.value = handle;
        endInput.value = '';
        return;
    }

    if (currentStart !== handle) {
        endInput.value = handle;
        return;
    }

    log('Select a different second instrument for pipe connection.');
}

async function refreshAfterModify() {
    // AutoCAD COM updates can land slightly after endpoint return; do short retries.
    for (let attempt = 1; attempt <= 3; attempt++) {
        try {
            await refreshEntities();
            return;
        } catch {
            // refreshEntities already logs failures
        }
        await sleep(150 * attempt);
    }
}

async function addSymbol() {
    const request = {
        block_name: document.getElementById('symbolType').value,
        x: parseFloat(document.getElementById('symbolX').value) || 0,
        y: parseFloat(document.getElementById('symbolY').value) || 0,
        scale: parseFloat(document.getElementById('symbolScale').value) || 100,
        rotation: parseFloat(document.getElementById('symbolRotation').value) || 0,
        layer: document.getElementById('symbolLayer').value || '0',
    };
    try {
        const entity = await fetchJson('/symbols', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(request),
        });
        log('Symbol inserted: ' + entity.handle);
        await refreshAfterModify();
    } catch (err) {
        log('Insert symbol failed: ' + err.message);
    }
}

async function deleteSymbol() {
    const handle = selectedHandleField.value;
    if (!handle) return log('Select a handle to delete.');
    try {
        await fetchJson('/entities/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({handle}),
        });
        log('Deleted entity: ' + handle);
        selectedHandleField.value = '';
        await refreshAfterModify();
    } catch (err) {
        log('Delete failed: ' + err.message);
    }
}

async function moveSymbol() {
    const handle = selectedHandleField.value;
    if (!handle) return log('Select a handle to move.');
    const request = {
        handle,
        dx: parseFloat(document.getElementById('moveDx').value) || 0,
        dy: parseFloat(document.getElementById('moveDy').value) || 0,
        dz: 0,
    };
    try {
        const entity = await fetchJson('/entities/move', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(request),
        });
        log('Moved entity: ' + entity.handle);
        await refreshAfterModify();
    } catch (err) {
        log('Move failed: ' + err.message);
    }
}

async function rotateSymbol() {
    const handle = selectedHandleField.value;
    if (!handle) return log('Select a handle to rotate.');
    const request = {
        handle,
        angle: parseFloat(document.getElementById('rotateAngle').value) || 0,
        base_x: 0,
        base_y: 0,
        base_z: 0,
    };
    try {
        const entity = await fetchJson('/entities/rotate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(request),
        });
        log('Rotated entity: ' + entity.handle);
        await refreshAfterModify();
    } catch (err) {
        log('Rotate failed: ' + err.message);
    }
}

async function connectPipe() {
    const startHandle = document.getElementById('startHandle').value.trim();
    const endHandle = document.getElementById('endHandle').value.trim();
    if (!startHandle || !endHandle) return log('Enter both start and end handles.');
    if (startHandle === endHandle) return log('Start and end handles must be different instruments.');
    try {
        const result = await fetchJson('/pipes/connect', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({start_handle: startHandle, end_handle: endHandle}),
        });
        log('Pipe connected: ' + result.connected);
        await refreshAfterModify();
    } catch (err) {
        log('Connect pipe failed: ' + err.message);
    }
}

async function countSymbols() {
    try {
        const result = await fetchJson('/count');
        log('Count: ' + result.count);
    } catch (err) {
        log('Count failed: ' + err.message);
    }
}

async function getDrawingDetails() {
    try {
        const details = await fetchJson('/drawing/details');
        log('Drawing details loaded.');
        detailsOutput.textContent = JSON.stringify(details, null, 2);
    } catch (err) {
        log('Get drawing details failed: ' + err.message);
    }
}

async function loadAvailableSymbols() {
    try {
        const symbols = await fetchJson('/symbols/available');
        const symbolSelect = document.getElementById('symbolType');
        symbolSelect.innerHTML = '';
        if (symbols && symbols.length > 0) {
            symbols.forEach(symbol => {
                const option = document.createElement('option');
                option.value = symbol;
                option.textContent = symbol;
                symbolSelect.appendChild(option);
            });
            log(`Loaded ${symbols.length} available symbols.`);
        } else {
            const option = document.createElement('option');
            option.value = '';
            option.textContent = 'No symbols available';
            symbolSelect.appendChild(option);
        }
    } catch (err) {
        log('Failed to load available symbols: ' + err.message);
        const symbolSelect = document.getElementById('symbolType');
        symbolSelect.innerHTML = '<option value="">Failed to load symbols</option>';
    }
}

function wireEvents() {
    document.getElementById('connectButton').addEventListener('click', connect);
    document.getElementById('refreshButton').addEventListener('click', refreshEntities);
    document.getElementById('countButton').addEventListener('click', countSymbols);
    document.getElementById('detailsButton').addEventListener('click', getDrawingDetails);
    document.getElementById('addSymbolButton').addEventListener('click', addSymbol);
    document.getElementById('deleteButton').addEventListener('click', deleteSymbol);
    document.getElementById('moveButton').addEventListener('click', moveSymbol);
    document.getElementById('rotateButton').addEventListener('click', rotateSymbol);
    document.getElementById('connectPipeButton').addEventListener('click', connectPipe);
    
    // Chat event listeners
    document.getElementById('agentChatButton').addEventListener('click', sendAgentChat);
    document.getElementById('agentChatInput').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            sendAgentChat();
        }
    });
}

async function sendAgentChat() {
    const chatInput = document.getElementById('agentChatInput');
    const message = chatInput.value.trim();
    
    if (!message) return;
    
    const chatLog = document.getElementById('chatLog');
    
    const userMsgDiv = document.createElement('div');
    userMsgDiv.className = 'chat-message user-message';
    userMsgDiv.innerHTML = `<strong>You:</strong> ${escapeHtml(message)}`;
    chatLog.appendChild(userMsgDiv);
    chatLog.scrollTop = chatLog.scrollHeight;
    
    const progressDiv = document.createElement('div');
    progressDiv.className = 'chat-message action-log';
    progressDiv.innerHTML = `<strong>Status:</strong> Planning...`;
    chatLog.appendChild(progressDiv);
    chatLog.scrollTop = chatLog.scrollHeight;

    chatInput.value = '';
    chatInput.disabled = true;
    
    try {
        console.log('[CHAT] Sending:', message);
        
        const response = await fetchJson('/agent/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message}),
        });
        
        console.log('[CHAT] Response:', response);
        
        progressDiv.innerHTML = `<strong>Status:</strong> Planning complete. Executing...`;

        const aiMsgDiv = document.createElement('div');
        aiMsgDiv.className = 'chat-message ai-message';
        aiMsgDiv.innerHTML = `<strong>AI:</strong> ${escapeHtml(response.response)}`;
        chatLog.appendChild(aiMsgDiv);

        if (response.thought) {
            const thoughtDiv = document.createElement('div');
            thoughtDiv.className = 'chat-message action-log';
            thoughtDiv.innerHTML = `<strong>Planner Thought:</strong> ${escapeHtml(response.thought)}`;
            chatLog.appendChild(thoughtDiv);
        }

        if (response.steps && response.steps.length > 0) {
            const planDiv = document.createElement('div');
            planDiv.className = 'chat-message action-log';
            planDiv.innerHTML = `<strong>Execution Plan:</strong><ol>${response.steps.map(step => `<li><strong>${escapeHtml(step.tool)}</strong> ${escapeHtml(JSON.stringify(step.args))}</li>`).join('')}</ol>`;
            chatLog.appendChild(planDiv);
        }

        if (response.execution_results && response.execution_results.length > 0) {
            const execDiv = document.createElement('div');
            execDiv.className = 'chat-message action-log';
            execDiv.innerHTML = `<strong>Execution Timeline:</strong><ol>${response.execution_results.map(item => `<li>[${escapeHtml(item.status)}] <strong>${escapeHtml(item.tool)}</strong> - ${escapeHtml(item.result?.message || (item.result?.error || JSON.stringify(item.result)))}</li>`).join('')}</ol>`;
            chatLog.appendChild(execDiv);
        }

        if (response.actions && response.actions.length > 0) {
            const actionDiv = document.createElement('div');
            actionDiv.className = 'chat-message action-log';
            actionDiv.innerHTML = '<strong>Actions Executed:</strong><br>' +
                response.actions.map(a => `<div class="action-item">${actionTypeIcon(a.type || a.tool)} ${formatAction(a)}</div>`).join('');
            chatLog.appendChild(actionDiv);
        }

        if (!response.success) {
            const errorDetails = response.execution_results?.find(item => item.status === 'failed')?.result?.error || response.tool_results?.find(r => r.error)?.error;
            const errorDiv = document.createElement('div');
            errorDiv.className = 'chat-message error-message';
            errorDiv.innerHTML = `<strong>⚠️ Error:</strong> ${escapeHtml(errorDetails || response.response)}`;
            chatLog.appendChild(errorDiv);
        }

        progressDiv.innerHTML = `<strong>Status:</strong> Completed ${response.success ? 'successfully' : 'with errors'}.`;
        chatLog.scrollTop = chatLog.scrollHeight;

        if (response.actions && response.actions.length > 0) {
            setTimeout(() => loadEntities(), 500);
        }
        
    } catch (err) {
        console.error('[CHAT] Error:', err);
        progressDiv.innerHTML = `<strong>Status:</strong> Failed.`;
        
        const errorDiv = document.createElement('div');
        errorDiv.className = 'chat-message error-message';
        errorDiv.innerHTML = `<strong>❌ Error:</strong> ${escapeHtml(err.message)}`;
        chatLog.appendChild(errorDiv);
        chatLog.scrollTop = chatLog.scrollHeight;
    } finally {
        chatInput.disabled = false;
        chatInput.focus();
    }
}

function actionTypeIcon(type) {
    const icons = {
        'insert_symbol': '➕',
        'count_entities': '🔢',
        'move_entity': '↔️',
        'rotate_entity': '🔄',
        'delete_entity': '🗑️',
        'connect_entities': '🔗',
        'query': '❓',
        'unknown': '•',
    };
    return icons[type] || '•';
}

function formatAction(action) {
    const type = action.type || action.tool || 'unknown';
    const status = action.status === 'failed' ? '✗' : '✓';
    const args = action.args || action;

    switch(type) {
        case 'insert_symbol':
            return `${status} Inserted <strong>${escapeHtml(args.block_name || args.symbol || 'symbol')}</strong> at (${escapeHtml(args.x || 0)}, ${escapeHtml(args.y || 0)})`;
        case 'count_entities':
            return `${status} Counted entities: <strong>${escapeHtml(args.count || action.result?.count || 'unknown')}</strong>`;
        case 'move_entity':
            return `${status} Moved <strong>${escapeHtml(args.entity || args.handle || 'entity')}</strong> by (${escapeHtml(args.dx || args.offset?.[0] || 0)}, ${escapeHtml(args.dy || args.offset?.[1] || 0)})`;
        case 'rotate_entity':
            return `${status} Rotated <strong>${escapeHtml(args.entity || args.handle || 'entity')}</strong> by ${escapeHtml(args.angle || 0)}°`;
        case 'delete_entity':
            return `${status} Deleted <strong>${escapeHtml(args.entity || args.handle || 'entity')}</strong>`;
        case 'connect_entities':
            return `${status} Connected <strong>${escapeHtml(args.from || 'unknown')}</strong> to <strong>${escapeHtml(args.to || 'unknown')}</strong>`;
        default:
            return `${status} ${escapeHtml(type)} ${escapeHtml(JSON.stringify(args))}`;
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

window.addEventListener('DOMContentLoaded', () => {
    statusBadge.textContent = 'Disconnected';
    statusBadge.style.color = 'crimson';
    wireEvents();
    loadAvailableSymbols();
    log('Frontend ready. Press Connect to initialize AutoCAD.');
});
