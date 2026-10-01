/**
 * Example: Integrating AxleSyncClient into your Axle UI
 * This shows how to use the sync client in your existing app
 */

// ============ INITIALIZATION ============

let sync = null;

async function initializeSync() {
  // Create sync client pointing to your Railway backend
  sync = new AxleSyncClient('https://your-backend.up.railway.app');
  
  // Try to restore from localStorage (already registered)
  if (!sync.restoreInstance()) {
    // First time: register this device
    await sync.register('My Desktop');
  }
  
  // Connect WebSocket for live updates
  sync.connectSocket();
  
  console.log('✓ Sync initialized');
  
  // Load any existing session
  const session = await sync.getSession();
  if (session) {
    loadConversationHistory(session.conversation_history);
  }
}

// ============ MEMORY MANAGEMENT ============

async function saveUserPreferences(prefs) {
  // Save as memory so both devices share it
  await sync.saveMemory('user-setup', 'preferences', prefs);
}

async function loadUserPreferences() {
  try {
    const mem = await sync.getMemoryKey('user-setup', 'preferences');
    return mem.value;
  } catch {
    return {};
  }
}

async function updateProjectStatus(project, status) {
  // Keep project status in sync across devices
  await sync.saveMemory('project-status', project, {
    status: status,
    updated_at: new Date().toISOString()
  });
}

// Listen for memory updates from other devices
sync.onMemoryUpdate((data) => {
  console.log('📝 Another device updated memory:', data.memory.key);
  
  // Refresh UI if needed
  if (data.memory.category === 'project-status') {
    loadProjectStatus(data.memory.key);
  }
});

// ============ CONVERSATION SYNC ============

const conversationHistory = [];

async function sendMessage(userMessage) {
  // Add to local history
  conversationHistory.push({
    role: 'user',
    content: userMessage,
    timestamp: new Date().toISOString()
  });
  
  // Save to backend (so other device can see it)
  await sync.appendToHistory({
    role: 'user',
    content: userMessage,
    timestamp: new Date().toISOString()
  });
  
  // Call your Gemini API or Axle AI here
  const response = await callAxleAI(userMessage, conversationHistory);
  
  // Add assistant response
  conversationHistory.push({
    role: 'assistant',
    content: response,
    timestamp: new Date().toISOString()
  });
  
  // Save response to backend
  await sync.appendToHistory({
    role: 'assistant',
    content: response,
    timestamp: new Date().toISOString()
  });
  
  // Also save entire session state
  await sync.saveSession(
    { 
      user: 'Shane',
      current_task: getCurrentTask(),
      device: 'desktop'
    },
    conversationHistory
  );
  
  return response;
}

// Listen for history updates from other devices
sync.onHistoryUpdate((data) => {
  console.log('📨 Other device sent message:', data.message.role);
  
  // Could auto-scroll, notify user, etc.
  if (data.message.role === 'user') {
    displayRemoteUserMessage(data.message.content);
  }
});

function loadConversationHistory(history) {
  conversationHistory.length = 0;
  conversationHistory.push(...history);
  
  // Render in UI
  renderConversation();
}

// ============ SESSION RESTORATION ============

async function restoreSessionFromOtherDevice() {
  try {
    const session = await sync.getSession();
    const memory = await sync.getMemory();
    
    console.log('Restoring session...');
    console.log('- Conversation:', session.conversation_history.length, 'messages');
    console.log('- Memory:', memory.length, 'entries');
    
    // Load conversation
    loadConversationHistory(session.conversation_history);
    
    // Load user preferences
    const prefs = memory.find(m => m.category === 'user-setup' && m.key === 'preferences');
    if (prefs) {
      applyUserPreferences(prefs.value);
    }
    
    // Load current project
    const projects = memory.filter(m => m.category === 'project-status');
    projects.forEach(p => {
      addProjectToUI(p.key, p.value.status);
    });
    
    console.log('✓ Session restored');
  } catch (error) {
    console.error('Failed to restore session:', error);
  }
}

// ============ MULTI-DEVICE WORKFLOW ============

async function switchDevices() {
  // Before closing this instance, save final state
  console.log('Saving state before close...');
  
  await sync.saveSession(
    {
      user: 'Shane',
      last_active_device: 'desktop',
      closed_at: new Date().toISOString()
    },
    conversationHistory
  );
  
  // Save any open projects
  const currentProject = getCurrentProject();
  if (currentProject) {
    await sync.saveMemory('project-status', currentProject, {
      status: 'paused',
      device: 'desktop',
      saved_at: new Date().toISOString()
    });
  }
  
  console.log('✓ State saved. Switch to another device.');
}

async function resumeOnNewDevice() {
  // On new device, restore everything
  await restoreSessionFromOtherDevice();
  
  // Check for recent work
  const recentWork = await sync.getMemoryCategory('project-status');
  console.log('Recent work:', recentWork);
  
  // Let user know they can continue
  showNotification('Welcome back! Restoring your work...');
}

// ============ HELPER FUNCTIONS ============

function getCurrentTask() {
  // Return what user is currently working on
  return 'almindo_redesign';
}

function getCurrentProject() {
  return document.getElementById('current-project')?.value;
}

async function callAxleAI(message, history) {
  // Your Gemini API call here
  return 'Response from Axle';
}

function renderConversation() {
  const container = document.getElementById('conversation');
  container.innerHTML = conversationHistory.map(msg => `
    <div class="message ${msg.role}">
      <p>${msg.content}</p>
      <small>${new Date(msg.timestamp).toLocaleTimeString()}</small>
    </div>
  `).join('');
}

function displayRemoteUserMessage(content) {
  const elem = document.createElement('div');
  elem.className = 'message remote';
  elem.innerHTML = `<p>[From other device] ${content}</p>`;
  document.getElementById('conversation').appendChild(elem);
}

function showNotification(text) {
  const notif = document.createElement('div');
  notif.className = 'notification';
  notif.textContent = text;
  document.body.appendChild(notif);
  setTimeout(() => notif.remove(), 3000);
}

function applyUserPreferences(prefs) {
  if (prefs.theme) document.documentElement.setAttribute('data-theme', prefs.theme);
  if (prefs.language) document.documentElement.lang = prefs.language;
}

function addProjectToUI(projectName, status) {
  const list = document.getElementById('projects');
  const item = document.createElement('li');
  item.textContent = `${projectName}: ${status}`;
  list.appendChild(item);
}

function loadProjectStatus(projectName) {
  console.log('Reloading project:', projectName);
  // Update UI with latest status
}

// ============ STARTUP ============

document.addEventListener('DOMContentLoaded', async () => {
  await initializeSync();
  
  // Check if we're resuming from another device
  if (isFirstTimeThisSession()) {
    await resumeOnNewDevice();
  }
});

function isFirstTimeThisSession() {
  return !sessionStorage.getItem('initialized');
}
