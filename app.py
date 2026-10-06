"""
Axle Multi-Instance Backend
Syncs memory, conversation state, and live updates across devices via WebSocket
"""
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
from datetime import datetime
import os
import hmac
import secrets
from dotenv import load_dotenv
import uuid

load_dotenv()

app = Flask(__name__)
CORS(app)

# Database config
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://user:password@localhost/axle_sync')
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-prod')

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# ==================== MODELS ====================

class Instance(db.Model):
    """Legacy-named sync account.

    Existing Instance rows are preserved as the shared account identity so the
    current memory/session data does not need a destructive database migration.
    Individual computers are represented by Device rows below.
    """
    __tablename__ = 'instances'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    api_key = db.Column(db.String(255), unique=True, nullable=False)
    device_name = db.Column(db.String(255), nullable=False)
    last_active = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    sessions = db.relationship('Session', backref='instance', lazy=True, cascade='all, delete-orphan')
    memory_entries = db.relationship('Memory', backref='instance', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'device_name': self.device_name,
            'last_active': self.last_active.isoformat(),
            'created_at': self.created_at.isoformat()
        }


class Device(db.Model):
    """One trusted Axle installation attached to a shared sync account."""
    __tablename__ = 'devices'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id = db.Column(db.String(36), db.ForeignKey('instances.id'), nullable=False, index=True)
    api_key = db.Column(db.String(255), unique=True, nullable=False)
    device_name = db.Column(db.String(255), nullable=False)
    last_active = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    account = db.relationship(
        'Instance',
        backref=db.backref('devices', lazy=True, cascade='all, delete-orphan')
    )

    def to_dict(self):
        return {
            'id': self.id,
            'account_id': self.account_id,
            'device_name': self.device_name,
            'last_active': self.last_active.isoformat(),
            'created_at': self.created_at.isoformat()
        }


class Session(db.Model):
    """Active conversation session state"""
    __tablename__ = 'sessions'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    instance_id = db.Column(db.String(36), db.ForeignKey('instances.id'), nullable=False)
    session_data = db.Column(db.JSON, default=lambda: {})
    conversation_history = db.Column(db.JSON, default=lambda: [])
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'instance_id': self.instance_id,
            'session_data': self.session_data,
            'conversation_history': self.conversation_history,
            'last_updated': self.last_updated.isoformat(),
            'created_at': self.created_at.isoformat()
        }


class Memory(db.Model):
    """Long-term memory entries (context, facts, categorized data)"""
    __tablename__ = 'memory'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    instance_id = db.Column(db.String(36), db.ForeignKey('instances.id'), nullable=False)
    category = db.Column(db.String(255), nullable=False)  # e.g., "user-setup", "project-status"
    key = db.Column(db.String(255), nullable=False)       # e.g., "preferred_name", "current_project"
    value = db.Column(db.JSON, nullable=False)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('instance_id', 'category', 'key', name='_instance_category_key_uc'),)
    
    def to_dict(self):
        return {
            'id': self.id,
            'category': self.category,
            'key': self.key,
            'value': self.value,
            'last_updated': self.last_updated.isoformat(),
            'created_at': self.created_at.isoformat()
        }


# ==================== AUTH ====================

def _account_key_matches(account):
    supplied_key = request.headers.get('X-API-Key', '')
    return bool(supplied_key and hmac.compare_digest(supplied_key, account.api_key))


def _device_for_request(account_id):
    device_id = request.headers.get('X-Device-ID', '')
    device_key = request.headers.get('X-Device-Key', '')
    if not device_id and not device_key:
        return None, None
    if not device_id or not device_key:
        return None, (jsonify({'error': 'Both X-Device-ID and X-Device-Key are required'}), 401)

    device = db.session.get(Device, device_id)
    if (
        not device
        or device.account_id != account_id
        or not hmac.compare_digest(device_key, device.api_key)
    ):
        return None, (jsonify({'error': 'Unauthorized device'}), 401)
    return device, None


def require_account_key(account_id):
    """Require the shared account key for device-management operations."""
    account = db.session.get(Instance, account_id)
    if not account:
        return None, (jsonify({'error': 'Account not found'}), 404)
    if not _account_key_matches(account):
        return None, (jsonify({'error': 'Unauthorized'}), 401)
    account.last_active = datetime.utcnow()
    db.session.commit()
    return account, None


def require_instance(instance_id):
    """Authenticate access to a shared account.

    Preferred auth is a per-device ID/key pair. The original shared X-API-Key
    remains accepted for backwards compatibility while existing installations
    migrate to device credentials.
    """
    account = db.session.get(Instance, instance_id)
    if not account:
        return None, (jsonify({'error': 'Account not found'}), 404)

    device, device_error = _device_for_request(instance_id)
    if device_error:
        return None, device_error

    if device is not None:
        device.last_active = datetime.utcnow()
        account.last_active = datetime.utcnow()
        db.session.commit()
        return account, None

    if _account_key_matches(account):
        account.last_active = datetime.utcnow()
        db.session.commit()
        return account, None

    return None, (jsonify({'error': 'Unauthorized'}), 401)


def safe_socket_emit(event, payload, room):
    """Best-effort realtime notification.

    A WebSocket delivery problem must never turn an already-successful
    database write into an HTTP 500 response. Log the failure and let the
    REST request succeed; clients can still reconcile from PostgreSQL.
    """
    try:
        socketio.emit(event, payload, to=room)
    except Exception:
        app.logger.exception("Socket.IO emit failed for event %s", event)


# ==================== REST API ====================

@app.route('/api/register', methods=['POST'])
def register_instance():
    """Register a new device instance"""
    data = request.json
    device_name = data.get('device_name', 'Unknown Device')
    
    api_key = str(uuid.uuid4())
    instance = Instance(device_name=device_name, api_key=api_key)
    
    db.session.add(instance)
    db.session.commit()
    
    return jsonify({
        'id': instance.id,
        'api_key': api_key,
        'device_name': instance.device_name
    }), 201


@app.route('/api/instances/<instance_id>', methods=['GET'])
def get_instance(instance_id):
    """Get shared account info (legacy route name kept for compatibility)."""
    instance, error = require_instance(instance_id)
    if error:
        return error
    return jsonify(instance.to_dict()), 200


# ==================== DEVICE MANAGEMENT ====================

@app.route('/api/accounts/<account_id>/devices', methods=['POST'])
def register_device(account_id):
    """Create a unique credential for one trusted Axle installation."""
    account, error = require_account_key(account_id)
    if error:
        return error

    data = request.json or {}
    device_name = str(data.get('device_name') or 'Axle Device').strip()[:255] or 'Axle Device'
    device_key = secrets.token_urlsafe(32)
    device = Device(
        account_id=account.id,
        api_key=device_key,
        device_name=device_name,
    )
    db.session.add(device)
    db.session.commit()

    return jsonify({
        'account_id': account.id,
        'device_id': device.id,
        'device_key': device_key,
        'device_name': device.device_name,
    }), 201


@app.route('/api/accounts/<account_id>/devices', methods=['GET'])
def list_devices(account_id):
    """List trusted devices. Requires the shared account key."""
    account, error = require_account_key(account_id)
    if error:
        return error
    devices = Device.query.filter_by(account_id=account.id).order_by(Device.created_at.asc()).all()
    return jsonify([device.to_dict() for device in devices]), 200


@app.route('/api/accounts/<account_id>/devices/<device_id>', methods=['DELETE'])
def revoke_device(account_id, device_id):
    """Revoke one device credential without affecting shared memory."""
    account, error = require_account_key(account_id)
    if error:
        return error
    device = Device.query.filter_by(id=device_id, account_id=account.id).first()
    if not device:
        return jsonify({'error': 'Device not found'}), 404
    db.session.delete(device)
    db.session.commit()
    return jsonify({'status': 'revoked', 'device_id': device_id}), 200


# ==================== MEMORY ENDPOINTS ====================

@app.route('/api/memory/<instance_id>', methods=['GET'])
def get_memory(instance_id):
    """Get all memory entries for instance"""
    instance, error = require_instance(instance_id)
    if error:
        return error
    
    memories = Memory.query.filter_by(instance_id=instance_id).all()
    return jsonify([m.to_dict() for m in memories]), 200


@app.route('/api/memory/<instance_id>/<category>', methods=['GET'])
def get_memory_category(instance_id, category):
    """Get memory for a specific category"""
    instance, error = require_instance(instance_id)
    if error:
        return error
    
    memories = Memory.query.filter_by(instance_id=instance_id, category=category).all()
    return jsonify([m.to_dict() for m in memories]), 200


@app.route('/api/memory/<instance_id>/<category>/<key>', methods=['GET'])
def get_memory_key(instance_id, category, key):
    """Get specific memory entry"""
    instance, error = require_instance(instance_id)
    if error:
        return error

    memory = Memory.query.filter_by(
        instance_id=instance_id,
        category=category,
        key=key
    ).first()
    
    if not memory:
        return jsonify({'error': 'Memory entry not found'}), 404
    
    return jsonify(memory.to_dict()), 200


@app.route('/api/memory/<instance_id>', methods=['POST'])
def save_memory(instance_id):
    """Save or update memory entry"""
    instance, error = require_instance(instance_id)
    if error:
        return error
    
    data = request.json or {}
    category = data.get('category')
    key = data.get('key')
    value = data.get('value')
    
    if not all([category, key, value is not None]):
        return jsonify({'error': 'Missing category, key, or value'}), 400
    
    memory = Memory.query.filter_by(
        instance_id=instance_id,
        category=category,
        key=key
    ).first()
    
    if memory:
        memory.value = value
        memory.last_updated = datetime.utcnow()
    else:
        memory = Memory(
            instance_id=instance_id,
            category=category,
            key=key,
            value=value
        )
        db.session.add(memory)
    
    db.session.commit()
    
    # Realtime notification is best-effort; PostgreSQL is the source of truth.
    safe_socket_emit('memory_updated', {
        'instance_id': instance_id,
        'memory': memory.to_dict()
    }, instance_id)
    
    return jsonify(memory.to_dict()), 201


@app.route('/api/memory/<instance_id>/<category>/<key>', methods=['DELETE'])
def delete_memory(instance_id, category, key):
    """Delete memory entry"""
    instance, error = require_instance(instance_id)
    if error:
        return error

    memory = Memory.query.filter_by(
        instance_id=instance_id,
        category=category,
        key=key
    ).first()
    
    if not memory:
        return jsonify({'error': 'Memory entry not found'}), 404
    
    db.session.delete(memory)
    db.session.commit()
    
    safe_socket_emit('memory_deleted', {
        'instance_id': instance_id,
        'category': category,
        'key': key
    }, instance_id)
    
    return jsonify({'status': 'deleted'}), 200


# ==================== SESSION ENDPOINTS ====================

@app.route('/api/session/<instance_id>', methods=['GET'])
def get_session(instance_id):
    """Get current session state"""
    instance, error = require_instance(instance_id)
    if error:
        return error
    
    session = Session.query.filter_by(instance_id=instance_id).first()
    if not session:
        return jsonify({'error': 'No active session'}), 404
    
    return jsonify(session.to_dict()), 200


@app.route('/api/session/<instance_id>', methods=['POST'])
def create_or_update_session(instance_id):
    """Create or update session state"""
    instance, error = require_instance(instance_id)
    if error:
        return error
    
    data = request.json or {}
    session = Session.query.filter_by(instance_id=instance_id).first()
    
    if session:
        if 'session_data' in data:
            session.session_data = data['session_data']
        if 'conversation_history' in data:
            session.conversation_history = data['conversation_history']
        session.last_updated = datetime.utcnow()
    else:
        session = Session(
            instance_id=instance_id,
            session_data=data.get('session_data', {}),
            conversation_history=data.get('conversation_history', [])
        )
        db.session.add(session)
    
    db.session.commit()
    
    # Broadcast update
    safe_socket_emit('session_updated', {
        'instance_id': instance_id,
        'session': session.to_dict()
    }, instance_id)
    
    return jsonify(session.to_dict()), 201


@app.route('/api/session/<instance_id>/history', methods=['POST'])
def append_to_history(instance_id):
    """Append message to conversation history"""
    instance, error = require_instance(instance_id)
    if error:
        return error
    
    data = request.json or {}
    message = data.get('message')
    
    if not message:
        return jsonify({'error': 'Missing message'}), 400
    
    session = Session.query.filter_by(instance_id=instance_id).first()
    if not session:
        session = Session(instance_id=instance_id)
        db.session.add(session)
    
    # Reassign the JSON list so SQLAlchemy reliably detects the change.
    session.conversation_history = [*(session.conversation_history or []), message]
    session.last_updated = datetime.utcnow()
    db.session.commit()
    
    safe_socket_emit('history_updated', {
        'instance_id': instance_id,
        'message': message
    }, instance_id)
    
    return jsonify({'status': 'appended', 'total_messages': len(session.conversation_history)}), 201


# ==================== WEBSOCKET ====================

@socketio.on('connect')
def handle_connect():
    """Instance connected"""
    print(f'Client connected: {request.sid}')
    emit('connect_response', {'data': 'Connected to Axle Sync'})


@socketio.on('join_instance')
def on_join_instance(data):
    """Authenticate a device and join the shared account sync room."""
    data = data or {}
    account_id = data.get('account_id') or data.get('instance_id')
    account = db.session.get(Instance, account_id) if account_id else None
    if not account:
        emit('join_error', {'error': 'Account not found'})
        return

    device_id = data.get('device_id', '')
    device_key = data.get('device_key', '')
    if device_id or device_key:
        device = db.session.get(Device, device_id) if device_id else None
        if (
            not device
            or device.account_id != account_id
            or not device_key
            or not hmac.compare_digest(device_key, device.api_key)
        ):
            emit('join_error', {'error': 'Unauthorized device'})
            return
        device.last_active = datetime.utcnow()
        account.last_active = datetime.utcnow()
        db.session.commit()
        join_room(account_id)
        emit('joined', {
            'account_id': account_id,
            'device_id': device.id,
            'status': 'joined'
        })
        return

    # Legacy shared-key login remains available during migration.
    api_key = data.get('api_key', '')
    if not api_key or not hmac.compare_digest(api_key, account.api_key):
        emit('join_error', {'error': 'Unauthorized'})
        return

    join_room(account_id)
    emit('joined', {'account_id': account_id, 'status': 'joined', 'legacy_auth': True})


@socketio.on('disconnect')
def handle_disconnect():
    """Instance disconnected"""
    print(f'Client disconnected: {request.sid}')


# ==================== HEALTH CHECK ====================

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok', 'sync_identity_version': 3}), 200


# ==================== DB INITIALIZATION ====================

def init_db():
    """Create tables if they don't exist"""
    with app.app_context():
        db.create_all()
        print('Database tables initialized')


if __name__ == '__main__':
    init_db()
    socketio.run(app, host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=True)
