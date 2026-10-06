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
    """Represents an Axle device instance"""
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

def require_instance(instance_id):
    """Authenticate an instance using the X-API-Key header."""
    instance = db.session.get(Instance, instance_id)
    if not instance:
        return None, (jsonify({'error': 'Instance not found'}), 404)

    supplied_key = request.headers.get('X-API-Key', '')
    if not supplied_key or not hmac.compare_digest(supplied_key, instance.api_key):
        return None, (jsonify({'error': 'Unauthorized'}), 401)

    instance.last_active = datetime.utcnow()
    return instance, None


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
    """Get instance info"""
    instance, error = require_instance(instance_id)
    if error:
        return error
    return jsonify(instance.to_dict()), 200


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
    """Authenticate and join the instance-specific sync room."""
    data = data or {}
    instance_id = data.get('instance_id')
    api_key = data.get('api_key', '')
    instance = db.session.get(Instance, instance_id) if instance_id else None

    if not instance or not api_key or not hmac.compare_digest(api_key, instance.api_key):
        emit('join_error', {'error': 'Unauthorized'})
        return

    join_room(instance_id)
    emit('joined', {'instance_id': instance_id, 'status': 'joined'})


@socketio.on('disconnect')
def handle_disconnect():
    """Instance disconnected"""
    print(f'Client disconnected: {request.sid}')


# ==================== HEALTH CHECK ====================

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok'}), 200


# ==================== DB INITIALIZATION ====================

def init_db():
    """Create tables if they don't exist"""
    with app.app_context():
        db.create_all()
        print('Database tables initialized')


if __name__ == '__main__':
    init_db()
    socketio.run(app, host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=True)
