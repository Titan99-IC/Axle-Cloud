# Axle Multi-Instance Backend

Sync memory, conversation state, and session data across multiple Axle devices in real-time via WebSocket.

## Features

- **Memory Sync**: Save/retrieve long-term context (categorized, keyed)
- **Session State**: Persist active conversation, pick up where you left off
- **Live Updates**: WebSocket pushes changes to all connected instances
- **PostgreSQL**: Persistent storage on Railway
- **REST API**: Full CRUD for memory and sessions
- **Multi-Device**: Register laptop + desktop, sync automatically

## Architecture

```
Laptop (Axle Instance 1)  ──┐
                             ├──> Railway Backend (Flask + PostgreSQL)
Desktop (Axle Instance 2) ──┘        ↓
                            WebSocket (live push)
```

## Setup

### 1. Local Development

```bash
# Clone repo
git clone <your-repo>
cd axle-backend

# Install
pip install -r requirements.txt

# Copy .env
cp .env.example .env

# For local testing, use SQLite (simpler):
# In .env, set: DATABASE_URL=sqlite:///axle_sync.db

# Run
python app.py
```

Backend runs on `http://localhost:5000`

### 2. Railway Deployment

**Prerequisites**: GitHub account, Railway account

**Steps**:

1. **Push to GitHub**:
   ```bash
   git add .
   git commit -m "Axle backend"
   git push origin main
   ```

2. **Create Railway Project**:
   - Go to [railway.app](https://railway.app)
   - Click "New Project" → "Deploy from GitHub"
   - Select your repo

3. **Add PostgreSQL Plugin**:
   - In Railway dashboard, click "Add Service"
   - Select "PostgreSQL"
   - Railway auto-injects `DATABASE_URL` env var

4. **Set Environment Variables**:
   - In Railway project settings, add:
     - `SECRET_KEY`: Generate random string (e.g., `python -c "import secrets; print(secrets.token_hex(32))"`)
     - `FLASK_ENV`: `production`

5. **Deploy**:
   - Railway auto-deploys on push to `main`
   - Your backend is live at `https://<project-name>.up.railway.app`

## API Reference

### Register Instance

```bash
POST /api/register
{
  "device_name": "My Laptop"
}

# Response:
{
  "id": "uuid",
  "api_key": "api-key-uuid",
  "device_name": "My Laptop"
}
```

**Save this! Store in localStorage:**
```js
localStorage.setItem('axle_instance_id', id);
localStorage.setItem('axle_api_key', api_key);
```

### Memory CRUD

**Save memory**:
```bash
POST /api/memory/<instance_id>
{
  "category": "user-setup",
  "key": "preferred_name",
  "value": "Shane"
}
```

**Get all memory**:
```bash
GET /api/memory/<instance_id>
```

**Get by category**:
```bash
GET /api/memory/<instance_id>/<category>
```

**Get specific entry**:
```bash
GET /api/memory/<instance_id>/<category>/<key>
```

**Delete entry**:
```bash
DELETE /api/memory/<instance_id>/<category>/<key>
```

### Session CRUD

**Create/update session**:
```bash
POST /api/session/<instance_id>
{
  "session_data": { "current_task": "working_on_portfolio" },
  "conversation_history": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ]
}
```

**Get session**:
```bash
GET /api/session/<instance_id>
```

**Append to history**:
```bash
POST /api/session/<instance_id>/history
{
  "message": { "role": "user", "content": "Hi Axle" }
}
```

## Client Integration

### JavaScript (Browser)

1. Add to your HTML:
```html
<script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
<script src="client-sync.js"></script>
```

2. Initialize in your app:
```js
const sync = new AxleSyncClient('https://your-backend.up.railway.app');

// First time: register
const result = await sync.register('My Laptop');

// Or restore from localStorage:
sync.restoreInstance();

// Connect WebSocket
sync.connectSocket();

// Listen for updates
sync.onMemoryUpdate((data) => {
  console.log('Memory changed:', data);
});

// Save memory
await sync.saveMemory('user-setup', 'current_project', 'almindo_plumbing');

// Get session from other device
const session = await sync.getSession();
console.log(session.conversation_history);

// Update session
await sync.saveSession({ current_task: 'coding' }, session.conversation_history);
```

### Python (Desktop/CLI)

```python
import requests
import json

class AxleSyncClient:
    def __init__(self, backend_url, instance_id, api_key):
        self.url = backend_url.rstrip('/')
        self.instance_id = instance_id
        self.api_key = api_key

    def save_memory(self, category, key, value):
        response = requests.post(
            f'{self.url}/api/memory/{self.instance_id}',
            json={'category': category, 'key': key, 'value': value}
        )
        return response.json()

    def get_memory(self):
        response = requests.get(f'{self.url}/api/memory/{self.instance_id}')
        return response.json()

    def get_session(self):
        response = requests.get(f'{self.url}/api/session/{self.instance_id}')
        return response.json()

# Usage:
sync = AxleSyncClient(
    'https://your-backend.up.railway.app',
    'instance-id',
    'api-key'
)

memory = sync.get_memory()
print(memory)
```

## Real-Time Sync Flow

1. **Laptop saves memory**:
   ```js
   await sync.saveMemory('project-status', 'current_work', 'almindo_redesign');
   ```

2. **Backend broadcasts via WebSocket**:
   ```
   emit('memory_updated', { instance_id, memory })  → ALL connected clients
   ```

3. **Desktop receives instantly**:
   ```js
   sync.onMemoryUpdate((data) => {
     if (data.instance_id !== sync.instanceId) {
       // Update from another device!
       console.log('Laptop updated:', data.memory);
     }
   });
   ```

4. **Desktop fetches full session**:
   ```js
   const session = await sync.getSession();
   // Restore conversation, continue working
   ```

## Workflow: Laptop → Desktop

**On Laptop**:
```js
// Save current work
await sync.saveMemory('work-session', 'almindo_redesign', {
  current_section: 'hero',
  figma_link: 'https://...',
  next_steps: ['mobile responsive', 'CTA buttons']
});

// Save conversation history
await sync.saveSession(
  { user: 'Shane', active_project: 'almindo_plumbing' },
  conversationHistory
);
```

**On Desktop** (close laptop first):
```js
// Restore instance
sync.restoreInstance();

// Fetch latest session
const session = await sync.getSession();
const memory = await sync.getMemory();

// Load context
console.log('Resuming:', memory.find(m => m.key === 'almindo_redesign'));

// Continue conversation
const history = session.conversation_history;
// ... continue from there
```

## Debugging

Check backend health:
```bash
curl https://your-backend.up.railway.app/health
# { "status": "ok" }
```

View logs in Railway dashboard or:
```bash
# Local
python app.py  # Debug output

# Railway
railway logs -f
```

## Database Schema

```
instances
  id (UUID)
  api_key (unique)
  device_name
  last_active
  created_at

sessions
  id (UUID)
  instance_id (FK)
  session_data (JSON)
  conversation_history (JSON)
  last_updated
  created_at

memory
  id (UUID)
  instance_id (FK)
  category
  key
  value (JSON)
  last_updated
  created_at
  (unique: instance_id + category + key)
```

## Next Steps

- Add authentication (API key validation on all requests)
- Add encryption for sensitive memory data
- Implement conflict resolution (concurrent edits)
- Add memory versioning/history
- Build admin dashboard to view all instances
- Add rate limiting

## License

Internal use by Shane Rowand / Axle project
