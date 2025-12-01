"""
Adaptive Preference Testing System - Backend API
Version: 3.1 (Fixed & Enterprise-Ready)
Database: PostgreSQL with proper SQL integration
Framework: Flask with SQLAlchemy ORM
"""

from flask import Flask, request, jsonify, send_file, Response, send_from_directory
import io
import csv
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID, INET, JSONB, BYTEA
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import uuid
import os
import json
import numpy as np
from datetime import datetime, timedelta
import logging
from functools import wraps
import hashlib
import base64
import re

# Import auth functions - consolidated import
try:
    from backend.auth import require_auth, require_roles, jwt_issue_pair_token, jwt_decode_pair_token, jwt_encode
except ImportError:
    from auth import require_auth, require_roles, jwt_issue_pair_token, jwt_decode_pair_token, jwt_encode


# ============================================================================
# CONFIGURATION
# ============================================================================

app = Flask(__name__)
CORS(app, resources={
    r"/api/*": {
        "origins": os.environ.get('ALLOWED_ORIGINS','http://localhost:3000').split(','),
        "expose_headers": ["Content-Disposition"]}})

# Database configuration - FIXED: Proper error handling
database_url = os.environ.get('DATABASE_URL')
if not database_url:
    raise RuntimeError('DATABASE_URL environment variable is required')
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = (os.environ.get('FLASK_ENV') == 'development')  # Log SQL queries
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
    'pool_recycle': 3600,
    'pool_pre_ping': True
}

# File upload configuration
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max file size
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Security
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def _redact_headers(headers):
    out = {}
    for k,v in headers.items():
        if k.lower()=='authorization' and isinstance(v,str):
            out[k] = v[:10] + '…REDACTED'
        else:
            out[k] = v
    return out


# Initialize SQLAlchemy
db = SQLAlchemy(app)

# --- Runtime Governance Sentinel (env-gated) ---
if os.environ.get('APP_ENFORCE_GOVERNANCE') == '1':
    REQUIRED_GOV = [
        '.github/workflows/ci.yml',
        '.github/workflows/governance-guard.yml',
        'governance/Project_Constitution.md',
        'governance/release.keep.yml',
        'governance/deprecations.yml',
        'contracts/AUTH_CONTRACT.md',
        'contracts/CSV_EXPORT_CONTRACT.md',
        'contracts/SESSION_FLOW_CONTRACT.md',
        'contracts/MICROCONTRACTS.md',
        'ENVIRONMENT.md',
        'Dockerfile',
        'PROMPTS/CLAUDE_GUI_IMPROVEMENT.txt',
        'PROMPTS/GEMINI_RUTHLESS_v5_3.txt',
        'MANIFEST.sha256.txt',
        'REPO_STATS.txt'
    ]
    missing = [p for p in REQUIRED_GOV if not os.path.exists(os.path.join(os.path.dirname(__file__), '..', p))]
    if missing:
        raise RuntimeError(f'Governance enforcement active; missing: {missing}')
# --- End Sentinel ---

# Rate limiter
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    limiter = Limiter(get_remote_address, app=app, default_limits=[])
except Exception:
    class _NoLimiter:
        def limit(self, *a, **k):
            def deco(f): return f
            return deco
    limiter = _NoLimiter()

SESSIONS_RATE = os.environ.get('SESSIONS_RATE','10 per minute')
NEXT_RATE = os.environ.get('NEXT_RATE','120 per minute')
CHOICE_RATE = os.environ.get('CHOICE_RATE','240 per minute')


# ============================================================================
# MODELS (SQLAlchemy ORM)
# ============================================================================

class User(db.Model):
    __tablename__ = 'users'
    
    user_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(200))
    institution = db.Column(db.String(200))
    role = db.Column(db.String(50), default='researcher')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    email_verified = db.Column(db.Boolean, default=False)
    preferences = db.Column(JSONB, default={})
    
    # Relationships
    experiments = db.relationship('Experiment', back_populates='user', cascade='all, delete-orphan')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self):
        return {
            'user_id': str(self.user_id),
            'email': self.email,
            'username': self.username,
            'full_name': self.full_name,
            'institution': self.institution,
            'role': self.role,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Experiment(db.Model):
    __tablename__ = 'experiments'
    
    experiment_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False)
    
    # Basic Info
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    research_question = db.Column(db.Text)
    
    # Configuration
    num_stimuli = db.Column(db.Integer, nullable=False)
    max_trials = db.Column(db.Integer, nullable=False)
    min_trials = db.Column(db.Integer, default=10)
    
    # Algorithm Parameters
    epsilon = db.Column(db.Float, default=0.01)
    exploration_weight = db.Column(db.Float, default=0.1)
    prior_mean = db.Column(db.Float, default=0.0)
    prior_variance = db.Column(db.Float, default=1.0)
    convergence_threshold = db.Column(db.Float, default=0.05)
    
    # Session Settings
    max_session_duration_minutes = db.Column(db.Integer, default=30)
    inactivity_timeout_minutes = db.Column(db.Integer, default=5)
    show_progress = db.Column(db.Boolean, default=True)
    allow_breaks = db.Column(db.Boolean, default=True)
    break_interval = db.Column(db.Integer, default=20)
    enable_counterbalancing = db.Column(db.Boolean, default=True)
    
    # Instructions
    instructions = db.Column(db.Text)
    completion_message = db.Column(db.Text)
    
    # Status
    status = db.Column(db.String(20), default='draft')
    published_at = db.Column(db.DateTime)
    archived_at = db.Column(db.DateTime)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Metadata - renamed to avoid SQLAlchemy reserved name conflict
    experiment_metadata = db.Column('metadata', JSONB, default={})
    
    # Relationships
    user = db.relationship('User', back_populates='experiments')
    stimuli = db.relationship('Stimulus', back_populates='experiment', cascade='all, delete-orphan')
    sessions = db.relationship('Session', back_populates='experiment')
    
    def to_dict(self, include_stimuli=False):
        data = {
            'experiment_id': str(self.experiment_id),
            'user_id': str(self.user_id),
            'name': self.name,
            'description': self.description,
            'num_stimuli': self.num_stimuli,
            'max_trials': self.max_trials,
            'min_trials': self.min_trials,
            'epsilon': self.epsilon,
            'exploration_weight': self.exploration_weight,
            'show_progress': self.show_progress,
            'allow_breaks': self.allow_breaks,
            'break_interval': self.break_interval,
            'enable_counterbalancing': self.enable_counterbalancing,
            'instructions': self.instructions,
            'completion_message': self.completion_message,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'published_at': self.published_at.isoformat() if self.published_at else None,
            'estimated_duration_minutes': int((self.max_trials * 3.0) / 60.0),
            'experiment_metadata': self.experiment_metadata or {}

        }
        
        if include_stimuli:
            data['stimuli'] = [s.to_dict() for s in self.stimuli]
        
        return data


# ============================
# Stimulus Library API
# ============================

@app.route('/api/stimuli', methods=['GET'])
@require_auth
@require_roles(['admin', 'researcher'])
def list_stimuli():
    """List stimuli for the Stimulus Library view.

    Optional query param:
      - experiment_id: if supplied, restrict to that experiment only.
    """
    try:
        experiment_id = request.args.get('experiment_id')
        query = Stimulus.query
        if experiment_id:
            query = query.filter_by(experiment_id=experiment_id)

        # Order by upload time so newest are last
        stimuli = query.order_by(Stimulus.uploaded_at.asc()).all()

        return jsonify({'stimuli': [s.to_dict() for s in stimuli]})
    except Exception as e:
        logger.error(f"Error listing stimuli: {e}")
        return jsonify({'error': 'Failed to list stimuli'}), 500


@app.route('/api/stimuli/upload', methods=['POST'])
@require_auth
@require_roles(['admin', 'researcher'])
def upload_stimulus_library():
    """Upload a stimulus image for use in the library.

    This mirrors the existing /api/experiments/<experiment_id>/stimuli
    but uses a global /api/stimuli/upload entry-point.

    It EXPECTS an experiment_id in the form-data or query string.
    """
    try:
        # IMPORTANT: we still need to know which experiment this belongs to
        experiment_id = request.form.get('experiment_id') or request.args.get('experiment_id')
        if not experiment_id:
            return jsonify({'error': 'experiment_id is required to upload a stimulus'}), 400

        # Confirm the experiment exists
        experiment = Experiment.query.filter_by(experiment_id=experiment_id).first()
        if not experiment:
            return jsonify({'error': 'Experiment not found'}), 404

        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type'}), 400

        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"

        upload_folder = app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, unique_filename)
        file.save(file_path)

        checksum = calculate_file_checksum(file_path)
        file_size = os.path.getsize(file_path)

        stimulus = Stimulus(
            experiment_id=experiment_id,
            stimulus_name=filename,
            file_path=file_path,
            url=f"http://localhost:5000/uploads/{unique_filename}",
            file_size_bytes=file_size,
            mime_type=file.content_type,
            checksum_sha256=checksum,
        )

        db.session.add(stimulus)
        db.session.commit()

        log_audit(
            'stimulus_uploaded',
            'data',
            f'Uploaded stimulus via /api/stimuli/upload: {filename}',
            {'stimulus_id': str(stimulus.stimulus_id), 'file_size': file_size},
            experiment_id=experiment_id
        )

        return jsonify({'stimulus': stimulus.to_dict()}), 201

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error uploading stimulus via /api/stimuli/upload: {e}")
        return jsonify({'error': 'Failed to upload stimulus'}), 500


@app.route('/api/stimuli/<stimulus_id>', methods=['PUT'])
@require_auth
@require_roles(['admin', 'researcher'])
def update_stimulus_metadata(stimulus_id):
    """Update metadata (room_type, curvature, brightness, hue, tags) for a stimulus."""
    try:
        stimulus = Stimulus.query.filter_by(stimulus_id=stimulus_id).first()
        if not stimulus:
            return jsonify({'error': 'Stimulus not found'}), 404

        data = request.get_json() or {}

        # Update JSON metadata blob
        meta = dict(stimulus.stimulus_metadata or {})
        if 'room_type' in data:
            meta['room_type'] = data['room_type'] or None
        if 'curvature_level' in data:
            meta['curvature_level'] = data['curvature_level'] or None
        if 'brightness' in data:
            meta['brightness'] = data['brightness'] or None
        if 'hue' in data:
            meta['hue'] = data['hue'] or None
        stimulus.stimulus_metadata = meta

        # Update tags ARRAY column
        tags = data.get('tags')
        if tags is not None:
            cleaned = [str(t).strip() for t in tags if str(t).strip()]
            stimulus.tags = cleaned or None

        db.session.commit()
        return jsonify(stimulus.to_dict())

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating stimulus metadata: {e}")
        return jsonify({'error': 'Failed to update stimulus'}), 500


@app.route('/api/stimuli/<stimulus_id>/auto_tag', methods=['POST'])
@require_auth
@require_roles(['admin', 'researcher'])
def auto_tag_stimulus(stimulus_id):
    """Auto-generate tags for a stimulus.

    For now this is a stub that inspects the filename/metadata.
    Later you can replace this with a call into your image tagger / BN.
    """
    try:
        stimulus = Stimulus.query.filter_by(stimulus_id=stimulus_id).first()
        if not stimulus:
            return jsonify({'error': 'Stimulus not found'}), 404

        existing_tags = set(stimulus.tags or [])
        name = (stimulus.stimulus_name or '').lower()
        meta = stimulus.stimulus_metadata or {}

        # Naive heuristic rules – placeholder
        if 'curve' in name or 'arched' in name:
            existing_tags.add('curved')
        if 'blue' in name or meta.get('hue') == 'cool':
            existing_tags.add('blue')
        if meta.get('brightness') == 'bright':
            existing_tags.add('bright')
        if meta.get('brightness') == 'dark':
            existing_tags.add('dark')

        if not existing_tags:
            existing_tags.add('candidate')

        stimulus.tags = sorted(existing_tags)
        db.session.commit()

        return jsonify({'tags': stimulus.tags})

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error auto-tagging stimulus: {e}")
        return jsonify({'error': 'Failed to auto-tag stimulus'}), 500
    
@app.route('/api/stimuli/<stimulus_id>/assign_experiment', methods=['PATCH'])
@require_auth
@require_roles(['admin', 'researcher'])
def assign_stimulus_experiment(stimulus_id):
    """
    Reassign a stimulus to a different experiment.
    Body: { "experiment_id": "<uuid>" }
    """
    data = request.get_json() or {}
    new_experiment_id = data.get('experiment_id')
    if not new_experiment_id:
        return jsonify({'error': 'experiment_id is required'}), 400

    stim = Stimulus.query.filter_by(stimulus_id=stimulus_id).first()
    if not stim:
        return jsonify({'error': 'Stimulus not found'}), 404

    # ensure the target experiment exists
    exp = Experiment.query.filter_by(experiment_id=new_experiment_id).first()
    if not exp:
        return jsonify({'error': 'Target experiment not found'}), 404

    stim.experiment_id = new_experiment_id
    db.session.commit()
    return jsonify({'success': True, 'stimulus': stim.to_dict()})


@app.route('/api/experiments/<experiment_id>/archive', methods=['POST'])
@require_auth
@require_roles(['admin', 'researcher'])
def archive_experiment(experiment_id):
    """Soft-archive an experiment: hide from active lists but keep all data."""
    try:
        exp = Experiment.query.filter_by(experiment_id=experiment_id).first()
        if not exp:
            return jsonify({'error': 'Experiment not found'}), 404

        # Flip status and set archived_at
        exp.status = 'archived'
        exp.archived_at = datetime.utcnow()
        db.session.commit()

        log_audit(
            'experiment_archived',
            'experiment',
            f'Archived experiment: {exp.name}',
            {'experiment_id': str(exp.experiment_id)},
            experiment_id=exp.experiment_id
        )

        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error archiving experiment: {e}")
        return jsonify({'error': 'Failed to archive experiment'}), 500
    
from sqlalchemy import delete as sa_delete

@app.route('/api/experiments/<experiment_id>', methods=['DELETE'])
@require_auth
@require_roles(['admin', 'researcher'])
def delete_experiment(experiment_id):
    """
    Delete an experiment.

    Query param:
      - delete_data=1 → delete experiment AND all sessions / choices / stimuli / algorithm_state / audit logs.
      - delete_data=0 or omitted → only delete experiment row IF there are no sessions; otherwise 400.
    """
    delete_data_flag = request.args.get('delete_data', '0')
    delete_data = delete_data_flag in ('1', 'true', 'True', 'yes')

    try:
        # Load experiment once via ORM so we can verify it exists
        exp = Experiment.query.filter_by(experiment_id=experiment_id).first()
        if not exp:
            return jsonify({'error': 'Experiment not found'}), 404

        # Grab needed info *before* we delete anything
        exp_name = exp.name
        session_ids = [s.session_id for s in exp.sessions]

        # If caller didn't explicitly allow data deletion but there are sessions, block it
        if not delete_data and session_ids:
            return jsonify({
                'error': (
                    'Experiment has existing sessions; delete_data=1 is required to delete it. '
                    'Use /api/experiments/<id>/archive to hide it instead.'
                )
            }), 400

        # ---- Perform FK-safe bulk deletes using Core ----

        if delete_data and session_ids:
            # 1) Audit log rows tied to those sessions (FK depends on sessions)
            db.session.execute(
                sa_delete(AuditLog).where(AuditLog.session_id.in_(session_ids))
            )

            # 2) Choices linked to sessions
            db.session.execute(
                sa_delete(Choice).where(Choice.session_id.in_(session_ids))
            )

            # 3) AlgorithmState linked to sessions
            db.session.execute(
                sa_delete(AlgorithmState).where(AlgorithmState.session_id.in_(session_ids))
            )

            # 4) Sessions themselves
            db.session.execute(
                sa_delete(Session).where(Session.session_id.in_(session_ids))
            )

            # 4b) Choices linked directly to stimuli of this experiment (not tied to a session)
            db.session.execute(
                sa_delete(Choice).where(Choice.stimulus_a_id.in_(
                    db.session.query(Stimulus.stimulus_id).filter(Stimulus.experiment_id == experiment_id)
                ))
            )
            db.session.execute(
                sa_delete(Choice).where(Choice.stimulus_b_id.in_(
                    db.session.query(Stimulus.stimulus_id).filter(Stimulus.experiment_id == experiment_id)
                ))
            )

        # 5) Stimuli belonging to this experiment
        db.session.execute(
            sa_delete(Stimulus).where(Stimulus.experiment_id == experiment_id)
        )

        # 6) Any remaining audit log rows tied directly to this experiment
        db.session.execute(
            sa_delete(AuditLog).where(AuditLog.experiment_id == experiment_id)
        )

        # 7) Finally, delete the experiment record itself
        db.session.execute(
            sa_delete(Experiment).where(Experiment.experiment_id == experiment_id)
        )

        db.session.commit()

        # IMPORTANT: do NOT touch `exp` here; it refers to a row that no longer exists.
        # If you want to return its name, use exp_name which we captured before deleting.
        return jsonify({
            'success': True,
            'delete_data': delete_data,
            'experiment_id': experiment_id,
            'experiment_name': exp_name,
        })

    except Exception as e:
        db.session.rollback()
        app.logger.exception('Failed to delete experiment')
        return jsonify({'error': f'Failed to delete experiment: {str(e)}'}), 500

class Stimulus(db.Model):
    __tablename__ = 'stimuli'
    
    stimulus_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    experiment_id = db.Column(UUID(as_uuid=True), db.ForeignKey('experiments.experiment_id', ondelete='CASCADE'), nullable=False)
    
    stimulus_name = db.Column(db.String(200), nullable=False)
    display_order = db.Column(db.Integer)
    file_path = db.Column(db.String(500), nullable=False)
    url = db.Column(db.Text)
    file_size_bytes = db.Column(db.Integer)
    mime_type = db.Column(db.String(100))
    width_px = db.Column(db.Integer)
    height_px = db.Column(db.Integer)
    checksum_sha256 = db.Column(db.String(64))
    stimulus_metadata = db.Column('metadata', JSONB, default={})
    tags = db.Column(db.ARRAY(db.String))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    experiment = db.relationship('Experiment', back_populates='stimuli')
    
    def to_dict(self):
        meta = self.stimulus_metadata or {}
        return {
            'stimulus_id': str(self.stimulus_id),
            'stimulus_name': self.stimulus_name,
            # alias for GUI code that expects `filename`
            'filename': self.stimulus_name,
            'url': self.url,
            'file_size_bytes': self.file_size_bytes,
            'mime_type': self.mime_type,
            'width_px': self.width_px,
            'height_px': self.height_px,
            # Flattened metadata fields for the Stimulus Library UI
            'room_type': meta.get('room_type'),
            'curvature_level': meta.get('curvature_level'),
            'brightness': meta.get('brightness'),
            'hue': meta.get('hue'),
            # Tags are stored in the ARRAY column but exposed as a list
            'tags': self.tags or [],
            'experiment_id': str(self.experiment_id) if self.experiment_id else None,
        }



class Session(db.Model):
    __tablename__ = 'sessions'
    
    session_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    experiment_id = db.Column(UUID(as_uuid=True), db.ForeignKey('experiments.experiment_id', ondelete='RESTRICT'), nullable=False)
    
    session_token = db.Column(db.String(128), unique=True, nullable=False)
    subject_id = db.Column(db.String(100))
    status = db.Column(db.String(20), default='active')
    
    trials_completed = db.Column(db.Integer, default=0)
    trials_total = db.Column(db.Integer, nullable=False)
    current_trial = db.Column(db.Integer, default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    last_activity_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    total_time_seconds = db.Column(db.Integer, default=0)
    
    subject_metadata = db.Column(JSONB, default={})
    browser_info = db.Column(JSONB, default={})
    ip_address = db.Column(INET)
    
    consistency_score = db.Column(db.Float)
    attention_check_passed = db.Column(db.Boolean)
    
    # Relationships
    experiment = db.relationship('Experiment', back_populates='sessions')
    choices = db.relationship('Choice', back_populates='session', cascade='all, delete-orphan')
    algorithm_state = db.relationship('AlgorithmState', back_populates='session', uselist=False)
    
    def to_dict(self):
        progress = (self.trials_completed / self.trials_total * 100) if self.trials_total > 0 else 0
        return {
            'session_id': str(self.session_id),
            'session_token': self.session_token,
            'experiment_id': str(self.experiment_id),
            'subject_id': self.subject_id,
            'status': self.status,
            'trials_completed': self.trials_completed,
            'trials_total': self.trials_total,
            'progress_percentage': round(progress, 1),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'total_time_seconds': self.total_time_seconds,
            'attention_check_passed': self.attention_check_passed,
        }



class AlgorithmState(db.Model):
    __tablename__ = 'algorithm_state'
    
    state_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = db.Column(UUID(as_uuid=True), db.ForeignKey('sessions.session_id', ondelete='CASCADE'), nullable=False, unique=True)
    
    mu = db.Column(BYTEA, nullable=False)  # Preference means
    sigma = db.Column(BYTEA, nullable=False)  # Covariance matrix
    comparison_matrix = db.Column(BYTEA, nullable=False)
    
    trials_completed = db.Column(db.Integer, default=0)
    total_trials = db.Column(db.Integer, nullable=False)
    algorithm_version = db.Column(db.String(20), default='3.1')
    
    state_checksum = db.Column(db.String(64), nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    version = db.Column(db.Integer, default=1)
    
    # Relationships
    session = db.relationship('Session', back_populates='algorithm_state')


class Choice(db.Model):
    __tablename__ = 'choices'
    
    choice_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = db.Column(UUID(as_uuid=True), db.ForeignKey('sessions.session_id', ondelete='CASCADE'), nullable=False)
    
    trial_number = db.Column(db.Integer, nullable=False)
    
    stimulus_a_id = db.Column(UUID(as_uuid=True), db.ForeignKey('stimuli.stimulus_id'), nullable=False)
    stimulus_b_id = db.Column(UUID(as_uuid=True), db.ForeignKey('stimuli.stimulus_id'), nullable=False)
    chosen_stimulus_id = db.Column(UUID(as_uuid=True), db.ForeignKey('stimuli.stimulus_id'), nullable=False)
    
    response_time_ms = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    presentation_order = db.Column(db.String(10))
    break_before = db.Column(db.Boolean, default=False)
    
    # Relationships
    session = db.relationship('Session', back_populates='choices')


class AuditLog(db.Model):
    __tablename__ = 'audit_log'
    
    log_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.user_id'))
    experiment_id = db.Column(UUID(as_uuid=True), db.ForeignKey('experiments.experiment_id'))
    session_id = db.Column(UUID(as_uuid=True), db.ForeignKey('sessions.session_id'))
    
    event_type = db.Column(db.String(100), nullable=False)
    event_category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    details = db.Column(JSONB, default={})
    
    ip_address = db.Column(INET)
    user_agent = db.Column(db.Text)
    severity = db.Column(db.String(20), default='info')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def calculate_file_checksum(file_path):
    """Calculate SHA256 checksum of file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def log_audit(event_type, event_category, description, details=None, user_id=None, 
              experiment_id=None, session_id=None, severity='info'):
    """Log audit event to database."""
    try:
        audit = AuditLog(
            user_id=user_id,
            experiment_id=experiment_id,
            session_id=session_id,
            event_type=event_type,
            event_category=event_category,
            description=description,
            details=details or {},
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
            severity=severity
        )
        db.session.add(audit)
        db.session.commit()
    except Exception as e:
        logger.error(f"Failed to log audit: {e}")


def generate_session_token():
    """Generate cryptographically secure session token."""
    return base64.urlsafe_b64encode(os.urandom(64)).decode('utf-8')


def serialize_numpy(arr):
    """Serialize numpy array to bytes."""
    return arr.tobytes()


def deserialize_numpy(data, shape, dtype=np.float64):
    """Deserialize bytes to a *writeable* numpy array."""
    if data is None:
        # In case we ever call this before state is initialized
        return np.zeros(shape, dtype=dtype)
    
    arr = np.frombuffer(data, dtype=dtype).reshape(shape)
    # Copy so the result is writeable (np.frombuffer gives a read-only view)
    return arr.copy()


def _is_attention_stimulus(stimulus):
    """Check if stimulus is marked as attention check."""
    try:
        meta = getattr(stimulus, 'stimulus_metadata', {}) or {}
        return bool(meta.get('attention_marker', False))
    except Exception:
        return False


def _evaluate_session_quality(session, experiment):
    """Evaluate session quality based on attention checks and trial count."""
    try:
        excl = (experiment.experiment_metadata or {}).get('exclusion', {})
        attention_min_rate = float(excl.get('attention_min_rate', 0.75))
        min_trials = int(excl.get('min_trials', experiment.min_trials or 0))
        choices = Choice.query.filter_by(session_id=session.session_id).all() or []
        att_total = 0
        att_correct = 0
        
        for c in choices:
            a = Stimulus.query.filter_by(stimulus_id=c.stimulus_a_id).first()
            b = Stimulus.query.filter_by(stimulus_id=c.stimulus_b_id).first()
            a_mark = _is_attention_stimulus(a)
            b_mark = _is_attention_stimulus(b)
            
            if a_mark or b_mark:
                att_total += 1
                correct_id = a.stimulus_id if a_mark else b.stimulus_id
                if str(c.chosen_stimulus_id) == str(correct_id):
                    att_correct += 1
        
        att_rate = (att_correct/att_total) if att_total else 1.0
        session.attention_check_passed = (att_rate >= attention_min_rate)
        
        reasons = []
        if session.trials_completed < min_trials:
            reasons.append(f'low_trials:{session.trials_completed}<{min_trials}')
        if att_total and not session.attention_check_passed:
            reasons.append(f'low_attention:{att_rate:.2f}<{attention_min_rate:.2f}')
        
        if reasons:
            log_audit('session_exclusion', 'quality', 'Session flagged for exclusion',
                      {'reasons': reasons, 'attention_rate': att_rate},
                      session_id=session.session_id, experiment_id=session.experiment_id, 
                      severity='warning')
        
        db.session.commit()
    except Exception as e:
        logger.error(f"Quality evaluation error: {e}")


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route('/api/auth/dev_issue_token', methods=['POST'])
def dev_issue_token():
    """Development endpoint for issuing tokens (disabled in production)."""
    if os.environ.get('AUTH_DEV_ISSUE_TOKENS') != '1':
        return jsonify({'error': 'disabled'}), 403
    
    data = request.get_json() or {}
    role = data.get('role', 'researcher')
    sub = data.get('sub', 'dev-user')
    
    token = jwt_encode({'sub': sub, 'role': role}, exp_seconds=3600*8)
    return jsonify({'token': token, 'role': role})


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    try:
        # Test database connection
        db.session.execute(text('SELECT 1'))
        db_status = 'healthy'
    except Exception as e:
        db_status = f'unhealthy: {str(e)}'
    
    return jsonify({
        'status': 'healthy' if db_status == 'healthy' else 'degraded',
        'database': db_status,
        'version': '3.1'
    })


@app.route('/api/experiments', methods=['POST'])
@require_auth
@require_roles(['admin', 'researcher'])
def create_experiment():
    """Create new experiment."""
    data = request.get_json()
    print("DEBUG: create_experiment() CALLED", flush=True)
    try:
        data = request.get_json() or {}

        # Validate required fields
        required = ['name', 'num_stimuli', 'max_trials']
        for field in required:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        # --- NEW: get or create a dev user based on the JWT ---
        payload = getattr(request, "user", {}) or {}
        sub = payload.get("sub", "dev-user")
        role = payload.get("role", "researcher")

        # use sub as an email-ish identifier for dev
        dev_email = f"{sub}@example.com" if "@" not in sub else sub
        username = dev_email.split("@")[0]

        user = User.query.filter_by(email=dev_email).first()
        if not user:
            user = User(
                email=dev_email,
                username=username,
                role=role,
            )
            user.set_password("dev-password")
            db.session.add(user)
            db.session.flush()  # ensures user.user_id is available

        # Create experiment
        experiment = Experiment(
            user_id=user.user_id,
            name=data['name'],
            description=data.get('description'),
            num_stimuli=data['num_stimuli'],
            max_trials=data['max_trials'],
            min_trials=data.get('min_trials', 10),
            epsilon=data.get('epsilon', 0.01),
            exploration_weight=data.get('exploration_weight', 0.1),
            show_progress=data.get('show_progress', True),
            allow_breaks=data.get('allow_breaks', True),
            break_interval=data.get('break_interval', 20),
            enable_counterbalancing=data.get('enable_counterbalancing', True),
            instructions=data.get('instructions'),
            completion_message=data.get('completion_message'),
            status='draft',
            experiment_metadata=data.get('experiment_metadata') or {}

        )

        db.session.add(experiment)
        db.session.commit()

        logger.info(f"Experiment created: {experiment.experiment_id}")

        return jsonify({
            'success': True,
            'experiment': experiment.to_dict()
        }), 201

    except IntegrityError as e:
        db.session.rollback()
        logger.error(f"Integrity error creating experiment: {e}")
        return jsonify({'error': 'Database integrity error'}), 400

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating experiment: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/experiments/<experiment_id>', methods=['GET'])
def get_experiment(experiment_id):
    """Get experiment by ID."""
    try:
        experiment = Experiment.query.filter_by(experiment_id=experiment_id).first()
        
        if not experiment:
            return jsonify({'error': 'Experiment not found'}), 404
        
        return jsonify({
            'success': True,
            'experiment': experiment.to_dict(include_stimuli=True)
        })
        
    except Exception as e:
        logger.error(f"Error getting experiment: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/experiments/<experiment_id>', methods=['PUT'])
@require_auth
def update_experiment(experiment_id):
    data = request.get_json() or {}

    exp = Experiment.query.filter_by(experiment_id=experiment_id).first()
    if not exp:
        return jsonify({'error': 'Experiment not found'}), 404

    # Update only the fields you actually use in the GUI
    exp.name = data.get('name', exp.name)
    exp.description = data.get('description', exp.description)
    exp.max_trials = data.get('max_trials', exp.max_trials)
    exp.min_trials = data.get('min_trials', exp.min_trials)
    exp.show_progress = data.get('show_progress', exp.show_progress)
    exp.break_interval = data.get('break_interval', exp.break_interval)
    exp.instructions = data.get('instructions', exp.instructions)
    exp.completion_message = data.get('completion_message', exp.completion_message)

    # If you’re storing extra config in metadata:
    meta = exp.experiment_metadata or {}
    new_meta = data.get('experiment_metadata') or {}
    meta.update(new_meta)
    exp.experiment_metadata = meta

    db.session.commit()
    return jsonify({'experiment': exp.to_dict()})


@app.route('/api/experiments/<experiment_id>/stimuli', methods=['POST'])
@require_auth
@require_roles(['admin', 'researcher'])
def upload_stimulus(experiment_id):
    """Upload stimulus for experiment."""
    try:
        # Check experiment exists
        experiment = Experiment.query.filter_by(experiment_id=experiment_id).first()
        if not experiment:
            return jsonify({'error': 'Experiment not found'}), 404
        
        # Check file in request
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type'}), 400
        
        # Save file
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        file.save(file_path)
        
        # Calculate checksum
        checksum = calculate_file_checksum(file_path)
        
        # Get file size
        file_size = os.path.getsize(file_path)
        
        # Create stimulus record
        stimulus = Stimulus(
            experiment_id=experiment_id,
            stimulus_name=filename,
            file_path=file_path,
            url=f'http://localhost:5000/uploads/{unique_filename}',
            file_size_bytes=file_size,
            mime_type=file.content_type,
            checksum_sha256=checksum
        )
        
        db.session.add(stimulus)
        db.session.commit()
        
        log_audit(
            'stimulus_uploaded',
            'data',
            f'Uploaded stimulus: {filename}',
            {'stimulus_id': str(stimulus.stimulus_id), 'file_size': file_size},
            experiment_id=experiment_id
        )
        
        return jsonify({
            'success': True,
            'stimulus': stimulus.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error uploading stimulus: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    """Serve uploaded stimulus files."""
    upload_folder = app.config['UPLOAD_FOLDER']
    return send_from_directory(upload_folder, filename)


@app.route('/api/experiments/<experiment_id>/publish', methods=['POST'])
@require_auth
@require_roles(['admin', 'researcher'])
def publish_experiment(experiment_id):
    """Publish experiment (make it active)."""
    try:
        experiment = Experiment.query.filter_by(experiment_id=experiment_id).first()
        
        if not experiment:
            return jsonify({'error': 'Experiment not found'}), 404
        
        # Validate experiment is ready
        if len(experiment.stimuli) < 3:
            return jsonify({'error': 'Need at least 3 stimuli'}), 400
        
        if experiment.status == 'active':
            return jsonify({'error': 'Experiment already published'}), 400
        
        # Publish
        experiment.status = 'active'
        experiment.published_at = datetime.utcnow()
        db.session.commit()
        
        log_audit(
            'experiment_published',
            'experiment',
            f'Published experiment: {experiment.name}',
            {'experiment_id': str(experiment.experiment_id)},
            experiment_id=experiment.experiment_id
        )
        
        return jsonify({
            'success': True,
            'experiment': experiment.to_dict(),
            'subject_url': f'/frontend/subject_interface_complete.html?exp={experiment_id}'
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error publishing experiment: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/sessions', methods=['POST'])
@limiter.limit(SESSIONS_RATE)
def create_session():
    """Create new subject session."""
    try:
        data = request.get_json()
        experiment_id = data.get('experiment_id')
        
        if not experiment_id:
            return jsonify({'error': 'experiment_id required'}), 400
        
        # Get experiment
        experiment = Experiment.query.filter_by(experiment_id=experiment_id).first()
        if not experiment:
            return jsonify({'error': 'Experiment not found'}), 404
        
        if experiment.status != 'active':
            return jsonify({'error': 'Experiment not active'}), 400
        
        # Create session
        session = Session(
            experiment_id=experiment_id,
            session_token=generate_session_token(),
            trials_total=experiment.max_trials,
            subject_id=data.get('subject_id'),
            subject_metadata=data.get('subject_metadata', {}),
            browser_info=data.get('browser_info', {}),
            ip_address=request.remote_addr
        )
        
        db.session.add(session)
        db.session.flush()  # Get session_id
        
        # Initialize algorithm state
        n_stimuli = experiment.num_stimuli
        mu = np.zeros(n_stimuli)
        sigma = np.eye(n_stimuli) * experiment.prior_variance
        comparison_matrix = np.zeros((n_stimuli, n_stimuli))
        
        state = AlgorithmState(
            session_id=session.session_id,
            mu=serialize_numpy(mu),
            sigma=serialize_numpy(sigma),
            comparison_matrix=serialize_numpy(comparison_matrix),
            trials_completed=0,
            total_trials=experiment.max_trials,
            state_checksum=hashlib.sha256(mu.tobytes() + sigma.tobytes()).hexdigest()
        )
        
        db.session.add(state)
        db.session.commit()
        
        log_audit(
            'session_created',
            'session',
            f'Created session for experiment: {experiment.name}',
            {'session_id': str(session.session_id)},
            session_id=session.session_id,
            experiment_id=experiment_id
        )
        
        return jsonify({
            'success': True,
            'session': session.to_dict(),
            'session_token': session.session_token
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating session: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/sessions/<session_token>/next', methods=['GET'])
@limiter.limit(NEXT_RATE)
def get_next_pair(session_token):
    """Get next stimulus pair for session using Bayesian algorithm."""
    try:
        # Validate session first
        session = Session.query.filter_by(session_token=session_token).first()
        
        if not session:
            return jsonify({'error': 'Session not found'}), 404
        
        if session.status == 'complete':
            return jsonify({'complete': True})
        
        # Check if max trials reached
        if session.trials_completed >= session.trials_total:
            session.status = 'complete'
            session.completed_at = datetime.utcnow()
            db.session.commit()
            return jsonify({'complete': True})
        
        experiment = session.experiment
        stimuli = experiment.stimuli
        
        if len(stimuli) < 2:
            return jsonify({'error': 'Not enough stimuli'}), 400
        
        # Load algorithm state
        algo_state_record = AlgorithmState.query.filter_by(session_id=session.session_id).first()
        
        if not algo_state_record:
            return jsonify({'error': 'Algorithm state not found'}), 500
        
        # Deserialize Bayesian state
        from bayesian_adaptive import BayesianPreferenceState, PureBayesianAdaptiveSelector
        
        n_items = len(stimuli)
        bayesian_state = BayesianPreferenceState(n_items)
        bayesian_state.mu = deserialize_numpy(algo_state_record.mu, (n_items,))
        bayesian_state.Sigma = deserialize_numpy(algo_state_record.sigma, (n_items, n_items))
        bayesian_state.comparison_matrix = deserialize_numpy(algo_state_record.comparison_matrix, (n_items, n_items))
        
        # Select next pair using Bayesian algorithm
        selector = PureBayesianAdaptiveSelector(
            epsilon=experiment.epsilon,
            exploration_weight=experiment.exploration_weight
        )
        
        i, j = selector.select_next_pair(bayesian_state)
        
        # Get stimuli (sorted by display_order to ensure consistent indexing)
        stimuli_list = sorted(stimuli, key=lambda s: s.display_order or 0)
        pair = [stimuli_list[i], stimuli_list[j]]
        
        # Determine presentation order
        pres_order = 'AB'
        if experiment.enable_counterbalancing and np.random.rand() > 0.5:
            pair = [pair[1], pair[0]]
            pres_order = 'BA'
        
        # Generate pair token for validation
        pair_token = jwt_issue_pair_token({
            'session_id': str(session.session_id),
            'trial_number': session.current_trial + 1,
            'stimulus_a_id': str(pair[0].stimulus_id),
            'stimulus_b_id': str(pair[1].stimulus_id),
            'presentation_order': pres_order
        })
        
        return jsonify({
            'success': True,
            'trial_number': session.current_trial + 1,
            'stimulus_a': pair[0].to_dict(),
            'stimulus_b': pair[1].to_dict(),
            'presentation_order': pres_order,
            'pair_token': pair_token,
            'show_progress': experiment.show_progress,
            'progress_percentage': (session.trials_completed / session.trials_total * 100) if session.trials_total > 0 else 0
        })
        
    except Exception as e:
        logger.error(f"Error getting next pair: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/sessions/<session_token>/choice', methods=['POST'])
@limiter.limit(CHOICE_RATE)
def record_choice(session_token):
    """Record subject's choice and update Bayesian beliefs."""
    try:
        data = request.get_json()
        
        # Validate session
        session = Session.query.filter_by(session_token=session_token).first()
        if not session:
            return jsonify({'error': 'Session not found'}), 404
        
        # Validate pair token
        pair_token = data.get('pair_token')
        if not pair_token:
            return jsonify({'error': 'Missing pair_token'}), 400
        
        try:
            pt = jwt_decode_pair_token(pair_token)
        except Exception as e:
            return jsonify({'error': f'Invalid pair_token: {e}'}), 400
        
        # Verify token matches session
        if str(session.session_id) != pt.get('session_id') or (session.current_trial + 1) != pt.get('trial_number'):
            return jsonify({'error': 'pair_token/session mismatch'}), 400
        
        # Validate choice data
        required = ['stimulus_a_id', 'stimulus_b_id', 'chosen_stimulus_id', 'response_time_ms']
        for field in required:
            if field not in data:
                return jsonify({'error': f'Missing field: {field}'}), 400
        
        # Get stimuli to find their indices
        experiment = session.experiment
        stimuli_list = sorted(experiment.stimuli, key=lambda s: s.display_order or 0)
        
        # Find indices
        stimulus_a_idx = next((i for i, s in enumerate(stimuli_list) 
                              if str(s.stimulus_id) == data['stimulus_a_id']), None)
        stimulus_b_idx = next((i for i, s in enumerate(stimuli_list) 
                              if str(s.stimulus_id) == data['stimulus_b_id']), None)
        winner_idx = next((i for i, s in enumerate(stimuli_list) 
                          if str(s.stimulus_id) == data['chosen_stimulus_id']), None)
        
        if stimulus_a_idx is None or stimulus_b_idx is None or winner_idx is None:
            return jsonify({'error': 'Invalid stimulus IDs'}), 400
        
        # Load algorithm state
        algo_state_record = AlgorithmState.query.filter_by(session_id=session.session_id).first()
        
        if not algo_state_record:
            return jsonify({'error': 'Algorithm state not found'}), 500
        
        # Deserialize and update Bayesian state
        from bayesian_adaptive import BayesianPreferenceState, PureBayesianAdaptiveSelector
        
        n_items = len(stimuli_list)
        bayesian_state = BayesianPreferenceState(n_items)
        bayesian_state.mu = deserialize_numpy(algo_state_record.mu, (n_items,))
        bayesian_state.Sigma = deserialize_numpy(algo_state_record.sigma, (n_items, n_items))
        bayesian_state.comparison_matrix = deserialize_numpy(algo_state_record.comparison_matrix, (n_items, n_items))
        
        # Update beliefs based on choice
        selector = PureBayesianAdaptiveSelector(
            epsilon=experiment.epsilon,
            exploration_weight=experiment.exploration_weight
        )
        
        bayesian_state = selector.update_beliefs(
            bayesian_state, 
            stimulus_a_idx, 
            stimulus_b_idx, 
            winner_idx
        )
        
        # Serialize updated state
        algo_state_record.mu = serialize_numpy(bayesian_state.mu)
        algo_state_record.sigma = serialize_numpy(bayesian_state.Sigma)
        algo_state_record.comparison_matrix = serialize_numpy(bayesian_state.comparison_matrix)
        algo_state_record.trials_completed += 1
        algo_state_record.updated_at = datetime.utcnow()
        algo_state_record.state_checksum = hashlib.sha256(
            bayesian_state.mu.tobytes() + bayesian_state.Sigma.tobytes()
        ).hexdigest()
        
        # Create choice record
        choice = Choice(
            session_id=session.session_id,
            trial_number=session.current_trial + 1,
            stimulus_a_id=data['stimulus_a_id'],
            stimulus_b_id=data['stimulus_b_id'],
            chosen_stimulus_id=data['chosen_stimulus_id'],
            response_time_ms=data['response_time_ms'],
            presentation_order=pt.get('presentation_order'),
            break_before=data.get('break_before', False)
        )
        
        db.session.add(choice)
        
        # Update session
        session.trials_completed += 1
        session.current_trial += 1
        session.last_activity_at = datetime.utcnow()
        session.total_time_seconds = int((datetime.utcnow() - session.started_at).total_seconds()) if session.started_at else 0
        
        # Check convergence
        if selector.check_convergence(bayesian_state, experiment.convergence_threshold):
            session.status = 'complete'
            session.completed_at = datetime.utcnow()
            _evaluate_session_quality(session, experiment)
        elif session.trials_completed >= session.trials_total:
            session.status = 'complete'
            session.completed_at = datetime.utcnow()
            _evaluate_session_quality(session, experiment)
        
        db.session.commit()
        
        log_audit(
            'choice_recorded',
            'data',
            f'Choice recorded: trial {choice.trial_number}',
            {'choice_id': str(choice.choice_id), 'winner': winner_idx},
            session_id=session.session_id
        )
        
        return jsonify({
            'success': True,
            'complete': session.status == 'complete'
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error recording choice: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/experiments/<experiment_id>/results', methods=['GET'])
@require_auth
@require_roles(['admin', 'researcher'])
def get_results(experiment_id):
    """Get experiment results."""
    try:
        experiment = Experiment.query.filter_by(experiment_id=experiment_id).first()
        
        if not experiment:
            return jsonify({'error': 'Experiment not found'}), 404
        
        # Get sessions
        sessions = Session.query.filter_by(experiment_id=experiment_id).all()
        
        # Get all choices
        session_ids = [s.session_id for s in sessions]
        choices = Choice.query.filter(Choice.session_id.in_(session_ids)).all()
        
        # Calculate statistics
        results = {
            'experiment': experiment.to_dict(),
            'summary': {
                'total_sessions': len(sessions),
                'completed_sessions': sum(1 for s in sessions if s.status == 'complete'),
                'active_sessions': sum(1 for s in sessions if s.status == 'active'),
                'total_choices': len(choices),
                'avg_response_time_ms': sum(c.response_time_ms for c in choices) / len(choices) if choices else 0
            },
            'sessions': [s.to_dict() for s in sessions]
        }
        
        return jsonify(results)
        
    except Exception as e:
        logger.error(f"Error getting results: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/experiments/all', methods=['GET'])
@require_auth
@require_roles(['admin', 'researcher'])
def get_all_experiments():
    """Get all experiments for the admin dashboard."""
    try:
        experiments = db.session.query(
            Experiment,
            db.func.count(Session.session_id).label('session_count')
        ).outerjoin(Session, Experiment.experiment_id == Session.experiment_id)\
         .filter(Experiment.archived_at.is_(None)) \
         .group_by(Experiment.experiment_id).order_by(Experiment.created_at.desc()).all()

        results = []
        for exp, count in experiments:
            exp_data = exp.to_dict()
            exp_data['session_count'] = count
            results.append(exp_data)

        return jsonify({'success': True, 'experiments': results})
    except Exception as e:
        logger.error(f"Error getting all experiments: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/experiments/<experiment_id>/export_choices_csv', methods=['GET'])
@require_auth
@require_roles(['admin', 'researcher'])
def export_choices_csv(experiment_id):
    """Export all choices for an experiment as a CSV file."""
    try:
        experiment = Experiment.query.filter_by(experiment_id=experiment_id).first()
        if not experiment:
            return jsonify({'error': 'Experiment not found'}), 404

        # Find all session IDs for this experiment
        session_ids = [s.session_id for s in experiment.sessions]
        if not session_ids:
            return jsonify({'error': 'No sessions found for this experiment'}), 404

        # Get all choices
        choices = Choice.query.filter(
            Choice.session_id.in_(session_ids)
        ).order_by(Choice.session_id, Choice.trial_number).all()

        if not choices:
            return jsonify({'error': 'No choices found for this experiment'}), 404

        # Create CSV in-memory
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            'session_id', 'subject_id', 'trial_number',
            'stimulus_a_id', 'stimulus_b_id', 'chosen_stimulus_id',
            'response_time_ms', 'timestamp', 'presentation_order'
        ])
        
        # Rows
        for choice in choices:
            writer.writerow([
                choice.session_id,
                getattr(choice.session, 'subject_id', None),
                choice.trial_number,
                choice.stimulus_a_id,
                choice.stimulus_b_id,
                choice.chosen_stimulus_id,
                choice.response_time_ms,
                choice.timestamp.isoformat() if getattr(choice, 'timestamp', None) else '',
                choice.presentation_order
            ])

        # Use experiment name as base for filename
        base_name = experiment.name or f"experiment_{experiment_id[:8]}"
        # slugify: keep only letters, numbers, underscores, dashes
        safe_name = re.sub(r'[^A-Za-z0-9_\-]+', '_', base_name).strip('_')

        filename = f"{safe_name}_choices_raw.csv"

        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except Exception as e:
        logger.error(f"Error exporting CSV: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/experiments/<experiment_id>/export_clean_choices_csv', methods=['GET'])
@require_auth
@require_roles(['admin', 'researcher'])
def export_clean_choices_csv(experiment_id):
    """Export a cleaned CSV with human-readable session and stimulus labels."""
    try:
        experiment = Experiment.query.filter_by(experiment_id=experiment_id).first()
        if not experiment:
            return jsonify({'error': 'Experiment not found'}), 404

        # Sessions ordered by creation time
        sessions = Session.query.filter_by(experiment_id=experiment_id) \
                                .order_by(Session.created_at.asc()).all()
        if not sessions:
            return jsonify({'error': 'No sessions found for this experiment'}), 404

        session_index = {s.session_id: idx + 1 for idx, s in enumerate(sessions)}

        # All stimuli for this experiment
        stimuli = Stimulus.query.filter_by(experiment_id=experiment_id).all()
        stim_by_id = {s.stimulus_id: s for s in stimuli}

        # All choices
        session_ids = [s.session_id for s in sessions]
        choices = Choice.query.filter(Choice.session_id.in_(session_ids)) \
                              .order_by(Choice.session_id, Choice.trial_number).all()
        if not choices:
            return jsonify({'error': 'No choices found for this experiment'}), 404

        # Helper to build simple session IDs
        base_code = (experiment.name or "EXP").upper()
        base_code = "".join(ch for ch in base_code if ch.isalnum())[:4] or "EXP"

        def simple_session_id(sess):
            idx = session_index.get(sess.session_id, 0)
            return f"{base_code}-S{idx:03d}"
        
        # Build CSV in-memory
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            'session_id',            
            'subject_id',
            'trial_number',
            'stimulus_a_name',
            'stimulus_b_name',
            'chosen_stimulus_name',
            'response_time_ms',
            'elapsed_ms_from_start',  
            'presentation_order',
            'chosen_side'
        ])
        
        # Rows
        for choice in choices:
            sess = choice.session
            s_a = stim_by_id.get(choice.stimulus_a_id)
            s_b = stim_by_id.get(choice.stimulus_b_id)
            s_c = stim_by_id.get(choice.chosen_stimulus_id)

            # Use started_at if available, else fall back to created_at
            start_time = sess.started_at or sess.created_at
            if choice.timestamp and start_time:
                elapsed_ms = int((choice.timestamp - start_time).total_seconds() * 1000)
            else:
                elapsed_ms = ''
            
            chosen_side = 'A' if choice.chosen_stimulus_id == choice.stimulus_a_id else 'B'

            writer.writerow([
                simple_session_id(sess),                    # session_id (clean)
                getattr(sess, 'subject_id', None),          # subject_id
                choice.trial_number,                        # trial_number
                s_a.stimulus_name if s_a else '',           # stimulus_a_name
                s_b.stimulus_name if s_b else '',           # stimulus_b_name
                s_c.stimulus_name if s_c else '',           # chosen_stimulus_name
                choice.response_time_ms,                    # response_time_ms (per-trial RT)
                elapsed_ms,                                 # elapsed_ms_from_start
                choice.presentation_order,                  # 'AB' or 'BA'
                chosen_side,
            ])

        # Use experiment name as base for filename
        base_name = experiment.name or f"experiment_{experiment_id[:8]}"
        # slugify: keep only letters, numbers, underscores, dashes
        safe_name = re.sub(r'[^A-Za-z0-9_\-]+', '_', base_name).strip('_')

        filename = f"{safe_name}_choices_clean.csv"

        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except Exception as e:
        logger.error(f"Error exporting clean CSV: {e}")
        return jsonify({'error': str(e)}), 500


# Consent and debrief document endpoints
CONSENT_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), '..', 'docs', 'consent_default.html')
DEBRIEF_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), '..', 'docs', 'debrief_default.html')


def _current_consent_path():
    """Get path to current consent document."""
    for name in ('consent.html', 'consent.pdf'):
        p = os.path.join(app.config.get('UPLOAD_FOLDER', '/tmp'), name)
        if os.path.exists(p):
            return p
    return os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'docs', 'consent_default.html'))


def _current_debrief_path():
    """Get path to current debrief document."""
    for name in ('debrief.html', 'debrief.pdf'):
        p = os.path.join(app.config.get('UPLOAD_FOLDER', '/tmp'), name)
        if os.path.exists(p):
            return p
    return os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'docs', 'debrief_default.html'))


@app.route('/api/consent', methods=['GET'])
def get_consent():
    """Serve consent document."""
    try:
        return send_file(_current_consent_path())
    except Exception as e:
        logger.error(f"Consent serve error: {e}")
        return jsonify({'error': 'Consent not available'}), 404


@app.route('/api/debrief', methods=['GET'])
def get_debrief():
    """Serve debrief document."""
    try:
        return send_file(_current_debrief_path())
    except Exception as e:
        logger.error(f"Debrief serve error: {e}")
        return jsonify({'error': 'Debrief not available'}), 404


@app.route('/api/admin/upload_consent', methods=['POST'])
@require_auth
@require_roles(['admin', 'researcher'])
def upload_consent():
    """Upload custom consent document."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file field'}), 400
    
    f = request.files['file']
    if not f or not f.filename:
        return jsonify({'error': 'Empty filename'}), 400
    
    filename = secure_filename(f.filename.lower())
    filename = 'consent.pdf' if filename.endswith('.pdf') else 'consent.html'
    dest = os.path.join(app.config.get('UPLOAD_FOLDER', '/tmp'), filename)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    f.save(dest)
    
    log_audit('consent_uploaded', 'admin', 'Uploaded consent file', {'filename': filename})
    return jsonify({'success': True, 'filename': filename})


@app.route('/api/admin/upload_debrief', methods=['POST'])
@require_auth
@require_roles(['admin', 'researcher'])
def upload_debrief():
    """Upload custom debrief document."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file field'}), 400
    
    f = request.files['file']
    if not f or not f.filename:
        return jsonify({'error': 'Empty filename'}), 400
    
    filename = secure_filename(f.filename.lower())
    filename = 'debrief.pdf' if filename.endswith('.pdf') else 'debrief.html'
    dest = os.path.join(app.config.get('UPLOAD_FOLDER', '/tmp'), filename)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    f.save(dest)
    
    log_audit('debrief_uploaded', 'admin', 'Uploaded debrief file', {'filename': filename})
    return jsonify({'success': True, 'filename': filename})


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def internal_error(e):
    db.session.rollback()
    safe_headers = _redact_headers(request.headers)
    logger.error(f"Internal error: {e} | headers={safe_headers}")
    return jsonify({'error': 'Internal server error'}), 500


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    # Create tables
    with app.app_context():
        db.create_all()
    
    # Run app
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=os.environ.get('FLASK_ENV') == 'development'
    )