/**
 * Axle Sync Client
 * Drop this into your Axle instance (browser or Node.js)
 * Handles memory and session sync with live WebSocket updates
 */

class AxleSyncClient {
  constructor(backendUrl, instanceId = null, apiKey = null) {
    this.backendUrl = backendUrl.replace(/\/$/, '');
    this.instanceId = instanceId;
    this.apiKey = apiKey;
    this.socket = null;
    this.callbacks = {};
  }

  /**
   * Register this device and get instance ID + API key
   */
  async register(deviceName) {
    try {
      const response = await fetch(`${this.backendUrl}/api/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device_name: deviceName })
      });
      
      if (!response.ok) throw new Error('Registration failed');
      
      const data = await response.json();
      this.instanceId = data.id;
      this.apiKey = data.api_key;
      
      // Store locally so you don't re-register
      localStorage.setItem('axle_instance_id', this.instanceId);
      localStorage.setItem('axle_api_key', this.apiKey);
      
      console.log('✓ Registered:', { id: this.instanceId, name: deviceName });
      return { id: this.instanceId, api_key: this.apiKey };
    } catch (error) {
      console.error('Register error:', error);
      throw error;
    }
  }

  /**
   * Restore instance from localStorage
   */
  restoreInstance() {
    const id = localStorage.getItem('axle_instance_id');
    const key = localStorage.getItem('axle_api_key');
    
    if (id && key) {
      this.instanceId = id;
      this.apiKey = key;
      console.log('✓ Restored instance:', id);
      return true;
    }
    return false;
  }

  /**
   * Connect WebSocket for live updates
   */
  connectSocket() {
    if (!this.instanceId) {
      console.error('No instance ID. Call register() first.');
      return;
    }

    // io() auto-detects protocol/host
    this.socket = io(this.backendUrl);

    this.socket.on('connect', () => {
      console.log('✓ WebSocket connected');
      this.socket.emit('join_instance', { instance_id: this.instanceId });
    });

    this.socket.on('memory_updated', (data) => {
      console.log('📝 Memory updated:', data);
      if (this.callbacks.onMemoryUpdate) {
        this.callbacks.onMemoryUpdate(data);
      }
    });

    this.socket.on('memory_deleted', (data) => {
      console.log('🗑️ Memory deleted:', data);
      if (this.callbacks.onMemoryDelete) {
        this.callbacks.onMemoryDelete(data);
      }
    });

    this.socket.on('session_updated', (data) => {
      console.log('💬 Session updated:', data);
      if (this.callbacks.onSessionUpdate) {
        this.callbacks.onSessionUpdate(data);
      }
    });

    this.socket.on('history_updated', (data) => {
      console.log('📨 History updated:', data);
      if (this.callbacks.onHistoryUpdate) {
        this.callbacks.onHistoryUpdate(data);
      }
    });
  }

  /**
   * Save memory entry
   */
  async saveMemory(category, key, value) {
    try {
      const response = await fetch(`${this.backendUrl}/api/memory/${this.instanceId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category, key, value })
      });
      
      if (!response.ok) throw new Error('Save failed');
      
      const data = await response.json();
      console.log('💾 Saved:', { category, key });
      return data;
    } catch (error) {
      console.error('Save memory error:', error);
      throw error;
    }
  }

  /**
   * Get all memory
   */
  async getMemory() {
    try {
      const response = await fetch(`${this.backendUrl}/api/memory/${this.instanceId}`);
      if (!response.ok) throw new Error('Fetch failed');
      return await response.json();
    } catch (error) {
      console.error('Get memory error:', error);
      throw error;
    }
  }

  /**
   * Get memory by category
   */
  async getMemoryCategory(category) {
    try {
      const response = await fetch(`${this.backendUrl}/api/memory/${this.instanceId}/${category}`);
      if (!response.ok) throw new Error('Fetch failed');
      return await response.json();
    } catch (error) {
      console.error('Get category error:', error);
      throw error;
    }
  }

  /**
   * Get specific memory entry
   */
  async getMemoryKey(category, key) {
    try {
      const response = await fetch(`${this.backendUrl}/api/memory/${this.instanceId}/${category}/${key}`);
      if (!response.ok) throw new Error('Fetch failed');
      return await response.json();
    } catch (error) {
      console.error('Get key error:', error);
      throw error;
    }
  }

  /**
   * Delete memory entry
   */
  async deleteMemory(category, key) {
    try {
      const response = await fetch(`${this.backendUrl}/api/memory/${this.instanceId}/${category}/${key}`, {
        method: 'DELETE'
      });
      if (!response.ok) throw new Error('Delete failed');
      console.log('🗑️ Deleted:', { category, key });
      return await response.json();
    } catch (error) {
      console.error('Delete memory error:', error);
      throw error;
    }
  }

  /**
   * Save session state (entire conversation)
   */
  async saveSession(sessionData, conversationHistory = []) {
    try {
      const response = await fetch(`${this.backendUrl}/api/session/${this.instanceId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_data: sessionData, conversation_history: conversationHistory })
      });
      
      if (!response.ok) throw new Error('Save failed');
      
      const data = await response.json();
      console.log('💬 Session saved');
      return data;
    } catch (error) {
      console.error('Save session error:', error);
      throw error;
    }
  }

  /**
   * Get active session
   */
  async getSession() {
    try {
      const response = await fetch(`${this.backendUrl}/api/session/${this.instanceId}`);
      if (!response.ok) throw new Error('No session');
      return await response.json();
    } catch (error) {
      console.error('Get session error:', error);
      return null;
    }
  }

  /**
   * Append message to conversation history
   */
  async appendToHistory(message) {
    try {
      const response = await fetch(`${this.backendUrl}/api/session/${this.instanceId}/history`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message })
      });
      
      if (!response.ok) throw new Error('Append failed');
      
      const data = await response.json();
      return data;
    } catch (error) {
      console.error('Append history error:', error);
      throw error;
    }
  }

  /**
   * Register callback for memory updates
   */
  onMemoryUpdate(callback) {
    this.callbacks.onMemoryUpdate = callback;
  }

  /**
   * Register callback for memory deletes
   */
  onMemoryDelete(callback) {
    this.callbacks.onMemoryDelete = callback;
  }

  /**
   * Register callback for session updates
   */
  onSessionUpdate(callback) {
    this.callbacks.onSessionUpdate = callback;
  }

  /**
   * Register callback for history updates
   */
  onHistoryUpdate(callback) {
    this.callbacks.onHistoryUpdate = callback;
  }

  /**
   * Disconnect WebSocket
   */
  disconnect() {
    if (this.socket) {
      this.socket.disconnect();
      console.log('✗ WebSocket disconnected');
    }
  }
}

// Export for use in browser or Node.js
if (typeof module !== 'undefined' && module.exports) {
  module.exports = AxleSyncClient;
}
