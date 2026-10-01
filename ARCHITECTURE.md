# Axle Backend Architecture

## Overview

Multi-instance sync system for Axle AI assistant across devices (laptop, desktop, etc.).

```
┌─────────────┐           ┌──────────────┐           ┌──────────────┐
│   Laptop    │           │   Desktop    │           │  Tablet      │
│ (Axle UI)   │           │  (Axle UI)   │           │ (Axle UI)    │
└──────┬──────┘           └──────┬───────┘           └──────┬───────┘
       │                         │                          │
       │ REST + WebSocket        │ REST + WebSocket         │
       └─────────┬───────────────┼──────────────────────────┘
                 │               │
         ┌───────▼───────────────▼────────┐
         │  Railway Backend                │
         │  ├─ Flask API Server           │
         │  ├─ WebSocket (Socket.io)      │
         │  └─ PostgreSQL Database        │
         │     ├─ Instances               │
         │     ├─ Sessions                │
         │     └─ Memory                  │
         └───────────────────────────────┘
```

## Components

### 1. Backend (Flask + SQLAlchemy)

**Models**:
- `Instance`: Device registration (laptop, desktop, etc.)
- `Session`: Active conversation state + history
- `Memory`: Long-term context (categorized, keyed)

**Features**:
- REST API for CRUD
- WebSocket for live push updates
- Timestamp tracking (last_updated)
- Relationships/cascading deletes

### 2. Database (PostgreSQL)

**Schemas**:

```sql
-- Instances (devices)
CREATE TABLE instances (
  id UUID PRIMARY KEY,
  api_key VARCHAR UNIQUE NOT NULL,
  device_name VARCHAR,
  last_active TIMESTAMP,
  created_at TIMESTAMP
);

-- Sessions (conversation state)
CREATE TABLE sessions (
  id UUID PRIMARY KEY,
  instance_id UUID FOREIGN KEY,
  session_data JSON,
  conversation_history JSON[],
  last_updated TIMESTAMP,
  created_at TIMESTAMP
);

-- Memory (long-term context)
CREATE TABLE memory (
  id UUID PRIMARY KEY,
  instance_id UUID FOREIGN KEY,
  category VARCHAR,
  key VARCHAR,
  value JSON,
  last_updated TIMESTAMP,
  created_at TIMESTAMP,
  UNIQUE(instance_id, category, key)
);
```

**Why PostgreSQL?**
- JSON support (native JSONB type)
- Relational integrity (FK constraints)
- Scalable & reliable
- Railway has managed Postgres

### 3. Client (JavaScript)

**AxleSyncClient**:
- REST endpoints for sync (fetch)
- WebSocket for live updates (Socket.io)
- localStorage for device persistence
- Callbacks for memory/session changes

**Methods**:
- `register()` → get instance ID
- `saveMemory()` / `getMemory()` → CRUD
- `saveSession()` / `getSession()` → conversation
- `connectSocket()` → listen to live updates

## Data Flow

### Scenario: Save Work on Laptop, Resume on Desktop

**Step 1: Laptop saves memory**
```
User: "I'm working on Almindo redesign hero section"
↓
sync.saveMemory('work-session', 'almindo', { current: 'hero', status: 'in_progress' })
↓
POST /api/memory/laptop-id
  { category: 'work-session', key: 'almindo', value: {...} }
↓
Backend: Save to DB, emit 'memory_updated' via WebSocket
↓
Desktop: Receives live update (if connected)
```

**Step 2: Laptop saves conversation**
```
User: [talks to Axle, gets feedback on design]
↓
sync.saveSession(
  { user: 'Shane', task: 'almindo', device: 'laptop' },
  conversationHistory
)
↓
POST /api/session/laptop-id
  { session_data: {...}, conversation_history: [...] }
↓
Backend: Update session, broadcast 'session_updated'
```

**Step 3: Desktop resumes**
```
User: (on desktop) "Continue from where I left off"
↓
sync.getSession()  // Fetch latest
↓
GET /api/session/laptop-id
  ← { session_data: {...}, conversation_history: [...] }
↓
Load conversation, restore memory, continue
```

## API Endpoints

### Instance Management
- `POST /api/register` → Create instance (get ID + key)
- `GET /api/instances/<id>` → Get instance info

### Memory (CRUD)
- `GET /api/memory/<instance>` → Get all
- `GET /api/memory/<instance>/<category>` → Get category
- `GET /api/memory/<instance>/<category>/<key>` → Get specific
- `POST /api/memory/<instance>` → Create/update
- `DELETE /api/memory/<instance>/<category>/<key>` → Delete

### Session (CRUD)
- `GET /api/session/<instance>` → Get state
- `POST /api/session/<instance>` → Create/update
- `POST /api/session/<instance>/history` → Append message

### Health
- `GET /health` → Server status

## WebSocket Events

**From Backend (broadcast)**:
- `memory_updated` → Any memory saved/updated
- `memory_deleted` → Memory deleted
- `session_updated` → Session changed
- `history_updated` → Message appended

**To Backend (client)**:
- `join_instance` → Join device-specific room

## Memory Organization

Example structure:

```json
{
  "category": "user-setup",
  "entries": [
    { "key": "name", "value": "Shane" },
    { "key": "location", "value": "Philadelphia" },
    { "key": "preferences", "value": { "theme": "dark", "tts": true } }
  ]
}

{
  "category": "project-status",
  "entries": [
    { "key": "almindo_plumbing", "value": { "status": "hero_done", "next": "mobile_responsive" } },
    { "key": "portfolio", "value": { "status": "deployed" } }
  ]
}

{
  "category": "voice-context",
  "entries": [
    { "key": "microphone_permission", "value": "granted" },
    { "key": "preferred_voice", "value": "male-en-US-1" }
  ]
}
```

Use categories to organize context logically. Clients fetch by category or key.

## Real-Time Sync Guarantees

- **No Guarantee of Order**: If laptop and desktop both update simultaneously, last one wins (timestamp based)
- **Eventual Consistency**: All instances sync within WebSocket latency (~100-500ms)
- **No Conflict Resolution**: Simple last-write-wins (can upgrade later)

## Security (Future)

- [ ] API key validation on all endpoints
- [ ] Rate limiting
- [ ] Encryption for sensitive fields (passwords, tokens)
- [ ] User authentication (JWT)
- [ ] Audit logging

## Deployment

- **Backend**: Flask on Railway (Procfile auto-detected)
- **Database**: PostgreSQL on Railway (auto-injected via DATABASE_URL)
- **Client**: Drop `client-sync.js` into any Axle instance
- **CI/CD**: Push to GitHub → Railway auto-deploys

## Monitoring

- Railway dashboard shows: logs, metrics, deployments
- Health check: `GET /health`
- Database stats: Railway PostgreSQL panel
- WebSocket connections: Flask logs

## Example: Full Workflow

```javascript
// On Laptop
const sync = new AxleSyncClient('https://backend.up.railway.app');
sync.register('Laptop');
sync.connectSocket();

// User works...
await sync.saveMemory('work', 'almindo', { current: 'hero_section' });
await sync.saveSession({ task: 'redesign' }, history);

// On Desktop (later)
const sync = new AxleSyncClient('https://backend.up.railway.app');
sync.restoreInstance(); // Uses localStorage to get ID
const session = await sync.getSession();
const memory = await sync.getMemory();
// Load context, continue work
```

That's it! Seamless sync.
