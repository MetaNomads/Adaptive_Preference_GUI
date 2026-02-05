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
import sqlite3

# Per-experiment settings DB + per-participant results DB helpers
try:
    from backend.experiment_fs import (
        get_experiment_paths, init_settings_db, init_participant_results_db,
        lookup_result_db_for_session, insert_session_index, mark_session_complete, slugify
    )
except ImportError:
    from experiment_fs import (
        get_experiment_paths, init_settings_db, init_participant_results_db,
        lookup_result_db_for_session, insert_session_index, mark_session_complete, slugify
    )


# Import auth functions - consolidated import
try:
    from backend.auth import require_auth, require_roles, jwt_issue_pair_token, jwt_decode_pair_token, jwt_encode
except ImportError:
    from auth import require_auth, require_roles, jwt_issue_pair_token, jwt_decode_pair_token, jwt_encode


# ============================================================================
# CONFIGURATION
# ============================================================================

app = Flask(__name__)
# Allow both localhost and the 127.0.0.1 IP on port 5000
CORS(app, resources={
    r"/api/*": {
        "origins": [
            "http://localhost:5000",
            "http://127.0.0.1:5000"
        ],
        "expose_headers": ["Content-Disposition"]
    }
})


# --- SINGLE SQLITE CORE DATABASE (no separate results DB) ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Store the core registry DB INSIDE experiments_data/_system instead of the repo root
SYSTEM_DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'experiments_data', '_system'))
os.makedirs(SYSTEM_DATA_DIR, exist_ok=True)

CORE_DB_PATH = os.path.join(SYSTEM_DATA_DIR, 'adaptive_preference_core.db')

# Core DB: users + experiments registry (portable)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'CORE_DATABASE_URL',
    f"sqlite:///{CORE_DB_PATH}"
)

# IMPORTANT:
# We no longer use a SQLAlchemy "results" bind DB.
# Results live in per-experiment/per-participant SQLite files created via sqlite3 (not SQLAlchemy binds).
# So DO NOT set SQLALCHEMY_BINDS here.


app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = (os.environ.get('FLASK_ENV') == 'development')

app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'connect_args': {'check_same_thread': False}
}


# File upload configuration
_default_upload = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'stimuli')
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', _default_upload)
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

# ============================================================================
# PER-EXPERIMENT SETTINGS DB + PER-PARTICIPANT RESULTS DB (SQLite files)
# ============================================================================
DATA_BASE_DIR = os.path.abspath(os.path.dirname(__file__))

def _exp_paths(experiment: 'Experiment') -> dict:
    """
    Compute experiment folder/db paths and ensure settings DB exists.
    IMPORTANT: This must be idempotent.
    If metadata already contains exp_storage and the folder/db exist, reuse it.
    """
    meta = experiment.experiment_metadata or {}
    storage = meta.get("exp_storage") or {}

    # If we already created storage before, REUSE it (do not create a new folder)
    exp_dir = storage.get("exp_dir")
    settings_db = storage.get("settings_db")
    stimuli_dir = storage.get("stimuli_dir")
    participants_dir = storage.get("participants_dir")

    # If we already created storage before, REUSE it (but verify it belongs to this experiment).
    if exp_dir and settings_db and os.path.exists(exp_dir) and os.path.exists(settings_db):
        # Guard against shared/incorrect metadata pointing at another experiment's folder.
        # (This can happen if JSON defaults were mutable, or if a folder was copied manually.)
        marker = os.path.join(exp_dir, ".experiment_id")
        try:
            if os.path.exists(marker):
                existing_id = open(marker, "r", encoding="utf-8").read().strip()
                if existing_id and existing_id != str(experiment.experiment_id):
                    # Treat as missing so we create fresh paths below.
                    exp_dir = None
        except Exception:
            exp_dir = None

    if exp_dir and settings_db and os.path.exists(exp_dir) and os.path.exists(settings_db):
        # Make sure subfolders exist (in case they were deleted manually)
        if stimuli_dir:
            os.makedirs(stimuli_dir, exist_ok=True)
        if participants_dir:
            os.makedirs(participants_dir, exist_ok=True)
        init_settings_db(settings_db)
        return storage


    # Otherwise create fresh paths
    exp_name = experiment.name or "experiment"
    paths = get_experiment_paths(DATA_BASE_DIR, str(experiment.experiment_id), exp_name)
    init_settings_db(paths["settings_db"])

    meta["exp_storage"] = {
        "exp_dir": paths["exp_dir"],
        "settings_db": paths["settings_db"],
        "stimuli_dir": paths["stimuli_dir"],
        "participants_dir": paths["participants_dir"],
        "exp_slug": paths["exp_slug"],
    }

    experiment.experiment_metadata = meta
    db.session.add(experiment)
    db.session.commit()

    return meta["exp_storage"]



def _get_settings_db_path(experiment: 'Experiment') -> str:
    meta = experiment.experiment_metadata or {}
    storage = meta.get("exp_storage") or {}
    settings_db = storage.get("settings_db")
    if settings_db and os.path.exists(settings_db):
        return settings_db
    # create if missing
    return _exp_paths(experiment)["settings_db"]


def _connect_sqlite(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("PRAGMA journal_mode=WAL;")
    return con


def _list_stimuli_from_settings(settings_db_path: str):
    con = _connect_sqlite(settings_db_path)
    try:
        rows = con.execute(
            "SELECT * FROM stimuli ORDER BY COALESCE(display_order,0), created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def _stimulus_row_to_dict(row: dict) -> dict:
    return {
        "stimulus_id": row.get("stimulus_id"),
        "filename": row.get("filename"),
        "file_path": row.get("file_path"),
        "mime_type": row.get("mime_type"),
        "display_order": row.get("display_order") or 0,
        "label": row.get("label"),
        "tags": json.loads(row.get("tags_json") or "[]"),
        "metadata": json.loads(row.get("metadata_json") or "{}"),
        "created_at": row.get("created_at"),
        # the frontend expects a URL it can load
        "url": f"/uploads/{os.path.basename(row.get('file_path') or '')}"
    }


def _participant_result_db_path(experiment: 'Experiment', subject_id: str, session_token: str) -> str:
    meta = experiment.experiment_metadata or {}
    storage = meta.get("exp_storage") or _exp_paths(experiment)
    exp_slug = storage.get("exp_slug") or slugify(experiment.name or "experiment")
    safe_subject = re.sub(r"[^a-zA-Z0-9_-]+", "_", (subject_id or "").strip())[:64]
    if not safe_subject:
        safe_subject = session_token[:12]
    filename = f"{exp_slug}_Result_{safe_subject}.db"
    return os.path.join(storage["participants_dir"], filename)


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
    
    user_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
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
    preferences = db.Column(db.JSON, default=dict)

    
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
    
    experiment_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False)
    
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
    experiment_metadata = db.Column('metadata', db.JSON, default=dict)

    
    # Relationships
    user = db.relationship('User', back_populates='experiments')
    stimuli = db.relationship('Stimulus', back_populates='experiment', cascade='all, delete-orphan')
    
    
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
            # Stimuli are stored in the per-experiment SETTINGS DB (not in the core SQLAlchemy Stimulus table).
            try:
                settings_db = _get_settings_db_path(self)
                rows = _list_stimuli_from_settings(settings_db)
                data['stimuli'] = [_stimulus_row_to_dict(r) for r in rows]
            except Exception:
                # Don't break the experiment fetch if a settings DB is missing/corrupt.
                data['stimuli'] = []

        
        return data


# ============================
# Stimulus Library API
# ============================
def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/api/stimuli', methods=['GET'])
@require_auth
@require_roles(['admin', 'researcher'])
def list_stimuli():
    """
    List stimuli for a specific experiment (stimuli live inside the per-experiment settings DB).
    Query param: ?experiment_id=<id>
    """
    try:
        experiment_id = request.args.get('experiment_id')
        if not experiment_id:
            return jsonify({'error': 'experiment_id required'}), 400

        experiment = Experiment.query.filter_by(experiment_id=experiment_id).first()
        if not experiment:
            return jsonify({'error': 'Experiment not found'}), 404

        settings_db = _get_settings_db_path(experiment)
        rows = _list_stimuli_from_settings(settings_db)
        stimuli = [_stimulus_row_to_dict(r) for r in rows]

        return jsonify({'success': True, 'stimuli': stimuli})
    except Exception as e:
        logger.error(f"Error listing stimuli: {e}")
        return jsonify({'error': str(e)}), 500

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/api/stimuli/upload', methods=['POST'])
@require_auth
@require_roles(['admin', 'researcher'])
def upload_stimulus_library():
    """
    Upload a stimulus into the experiment's own DB + folder.
    Form-data fields:
      - experiment_id (required)
      - file (required)
      - display_order (optional int)
      - label (optional)
    """
    try:
        experiment_id = request.form.get('experiment_id')
        if not experiment_id:
            return jsonify({'error': 'experiment_id required'}), 400

        experiment = Experiment.query.filter_by(experiment_id=experiment_id).first()
        if not experiment:
            return jsonify({'error': 'Experiment not found'}), 404

        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400

        file = request.files['file']
        if not file or file.filename == '':
            return jsonify({'error': 'No selected file'}), 400

        filename = secure_filename(file.filename)
        if '.' not in filename or filename.rsplit('.', 1)[1].lower() not in ALLOWED_EXTENSIONS:
            return jsonify({'error': f'Invalid file type. Allowed: {sorted(ALLOWED_EXTENSIONS)}'}), 400

        storage = experiment.experiment_metadata.get("exp_storage") if experiment.experiment_metadata else None
        if not storage:
            storage = _exp_paths(experiment)

        stimuli_dir = storage["stimuli_dir"]
        os.makedirs(stimuli_dir, exist_ok=True)

        # Ensure uniqueness on disk
        stimulus_id = str(uuid.uuid4())
        ext = filename.rsplit('.', 1)[1].lower()
        disk_name = f"{stimulus_id}.{ext}"
        file_path = os.path.join(stimuli_dir, disk_name)
        file.save(file_path)

        display_order = request.form.get('display_order')
        try:
            display_order = int(display_order) if display_order is not None and str(display_order).strip() != '' else 0
        except ValueError:
            display_order = 0

        label = request.form.get('label')

        settings_db = _get_settings_db_path(experiment)
        con = _connect_sqlite(settings_db)
        try:
            con.execute(
                """
                INSERT INTO stimuli(stimulus_id, filename, file_path, mime_type, display_order, label, tags_json, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stimulus_id, filename, file_path,
                    f"image/{ext}" if ext != "gif" else "image/gif",
                    display_order, label,
                    "[]", "{}", datetime.utcnow().isoformat()
                )
            )
            con.commit()
        finally:
            con.close()

        return jsonify({
            'success': True,
            'stimulus': {
                'stimulus_id': stimulus_id,
                'filename': filename,
                'display_order': display_order,
                'label': label,
                'url': f"/uploads/{disk_name}"
            }
        }), 201

    except Exception as e:
        logger.error(f"Error uploading stimulus: {e}")
        return jsonify({'error': str(e)}), 500

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

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

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

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

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

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

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

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
def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/api/experiments/<experiment_id>', methods=['DELETE'])
@require_auth
@require_roles(['admin', 'researcher'])
def delete_experiment(experiment_id):
    """
    Delete an experiment AND its attached stimuli/results on disk.
    This removes:
      - the experiment's folder (settings DB, stimuli files, participant DBs)
      - the experiment row in the core DB
    """
    try:
        experiment = Experiment.query.filter_by(experiment_id=experiment_id).first()
        if not experiment:
            return jsonify({'error': 'Experiment not found'}), 404

        meta = experiment.experiment_metadata or {}
        exp_storage = meta.get("exp_storage") or {}
        exp_dir = exp_storage.get("exp_dir")

        # Delete DB record first (so UI updates even if filesystem delete fails)
        db.session.delete(experiment)
        db.session.commit()

        # Then remove experiment folder (stimuli + participant DBs + settings DB)
        if exp_dir and os.path.exists(exp_dir):
            import shutil
            shutil.rmtree(exp_dir, ignore_errors=True)

        return jsonify({'success': True}), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting experiment: {e}")
        return jsonify({'error': str(e)}), 500


class Stimulus(db.Model):
    __tablename__ = 'stimuli'
    
    # REQUIRED: This must be set as primary_key=True
    stimulus_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    experiment_id = db.Column(db.String(36), db.ForeignKey('experiments.experiment_id', ondelete='CASCADE'), nullable=False)
    
    stimulus_name = db.Column(db.String(200), nullable=False)
    display_order = db.Column(db.Integer)
    file_path = db.Column(db.String(500), nullable=False)
    url = db.Column(db.Text)
    file_size_bytes = db.Column(db.Integer)
    mime_type = db.Column(db.String(100))
    width_px = db.Column(db.Integer)
    height_px = db.Column(db.Integer)
    checksum_sha256 = db.Column(db.String(64))
    stimulus_metadata = db.Column('metadata', db.JSON, default=dict)
    tags = db.Column(db.JSON, default=list)

    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    experiment = db.relationship('Experiment', back_populates='stimuli')
    
    def to_dict(self):
        meta = self.stimulus_metadata or {}
        # Ensure tags is always a list for the frontend
        current_tags = self.tags if isinstance(self.tags, list) else []
        return {
            'stimulus_id': str(self.stimulus_id),
            'stimulus_name': self.stimulus_name,
            'filename': self.stimulus_name,
            'url': self.url,
            'file_size_bytes': self.file_size_bytes,
            'mime_type': self.mime_type,
            'width_px': self.width_px,
            'height_px': self.height_px,
            'room_type': meta.get('room_type'),
            'curvature_level': meta.get('curvature_level'),
            'brightness': meta.get('brightness'),
            'hue': meta.get('hue'),
            'tags': current_tags,
            'experiment_id': str(self.experiment_id) if self.experiment_id else None,
        }

class Session(db.Model):
    __tablename__ = 'sessions'

    session_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # IMPORTANT: no ForeignKey here because Experiment lives in core DB
    experiment_id = db.Column(db.String(36), nullable=False, index=True)

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

    subject_metadata = db.Column(db.JSON, default=dict)
    browser_info = db.Column(db.JSON, default=dict)


    ip_address = db.Column(db.String(45))

    consistency_score = db.Column(db.Float)
    attention_check_passed = db.Column(db.Boolean)

    # Relationships inside results DB are fine:
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
    
    state_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = db.Column(db.String(36), db.ForeignKey('sessions.session_id', ondelete='CASCADE'), nullable=False, unique=True)
    
    # FIX: Changed BYTEA to LargeBinary for SQLite compatibility
    mu = db.Column(db.LargeBinary, nullable=False)
    sigma = db.Column(db.LargeBinary, nullable=False)
    comparison_matrix = db.Column(db.LargeBinary, nullable=False)
    
    trials_completed = db.Column(db.Integer, default=0)
    total_trials = db.Column(db.Integer, nullable=False)
    algorithm_version = db.Column(db.String(20), default='3.1')
    
    state_checksum = db.Column(db.String(64), nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    version = db.Column(db.Integer, default=1)
    
    session = db.relationship('Session', back_populates='algorithm_state')

class Choice(db.Model):
    __tablename__ = 'choices'

    choice_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = db.Column(db.String(36), db.ForeignKey('sessions.session_id', ondelete='CASCADE'), nullable=False)

    trial_number = db.Column(db.Integer, nullable=False)

    # IMPORTANT: no ForeignKey here because Stimulus lives in core DB
    stimulus_a_id = db.Column(db.String(36), nullable=False)
    stimulus_b_id = db.Column(db.String(36), nullable=False)
    chosen_stimulus_id = db.Column(db.String(36), nullable=False)

    response_time_ms = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    presentation_order = db.Column(db.String(10))
    break_before = db.Column(db.Boolean, default=False)

    session = db.relationship('Session', back_populates='choices')


class AuditLog(db.Model):
    __tablename__ = 'audit_log'

    log_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # IMPORTANT: no ForeignKey here because User/Experiment are in core DB
    user_id = db.Column(db.String(36))
    experiment_id = db.Column(db.String(36))
    session_id = db.Column(db.String(36))

    event_type = db.Column(db.String(100), nullable=False)
    event_category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    details = db.Column(db.JSON, default=dict)


    ip_address = db.Column(db.String(45))
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
def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/api/auth/dev_issue_token', methods=['POST'])
def dev_issue_token():
    """Forced active for offline use to allow easy admin access."""
    try:
        data = request.get_json() or {}
        role = data.get('role', 'researcher')
        sub = data.get('sub', 'dev-user')
        
        email = f"{sub}@example.com"
        user = User.query.filter_by(email=email).first()
        
        if not user:
            user = User(
                email=email, 
                username=sub, 
                role=role, 
                full_name="Local Admin", 
                is_active=True
            )
            user.set_password("dev-password")
            db.session.add(user)
            db.session.commit()
        
            token = jwt_encode({'sub': sub, 'role': role, 'user_id': str(user.user_id)}, exp_seconds=3600*8)

        
        # CRITICAL FIX: The str() below prevents the 500 Crash
        return jsonify({
            'token': token, 
            'role': role, 
            'user_id': str(user.user_id) 
        })
    except Exception as e:
        db.session.rollback()
        print(f"DEV LOGIN ERROR: {e}") # This prints to your terminal
        return jsonify({'error': str(e)}), 500
def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

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

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/api/experiments', methods=['POST'])
@require_auth
@require_roles(['admin', 'researcher'])
def create_experiment():
    """Create new experiment (and automatically create its settings DB + stimuli/results folders)."""
    try:
        data = request.get_json() or {}
        # require_auth sets request.user (dict). We need user_id from there.
        if not getattr(request, 'user', None) or not request.user.get('user_id'):
            return jsonify({'error': 'Missing user_id in token. Please dev login again.'}), 401

        # Validate required
        for field in ['name', 'num_stimuli', 'max_trials']:
            if field not in data:
                return jsonify({'error': f'Missing field: {field}'}), 400

        # Create experiment in CORE DB (users + experiment registry)
        exp = Experiment(
            user_id=request.user.get('user_id'),
            name=data['name'],
            description=data.get('description'),
            research_question=data.get('research_question'),
            num_stimuli=int(data['num_stimuli']),
            max_trials=int(data['max_trials']),
            min_trials=int(data.get('min_trials', 10)),
            epsilon=float(data.get('epsilon', 0.01)),
            exploration_weight=float(data.get('exploration_weight', 0.1)),
            prior_mean=float(data.get('prior_mean', 0.0)),
            prior_variance=float(data.get('prior_variance', 1.0)),
            convergence_threshold=float(data.get('convergence_threshold', 0.05)),
            max_session_duration_minutes=int(data.get('max_session_duration_minutes', 30)),
            inactivity_timeout_minutes=int(data.get('inactivity_timeout_minutes', 5)),
            show_progress=bool(data.get('show_progress', True)),
            allow_breaks=bool(data.get('allow_breaks', True)),
            break_interval=int(data.get('break_interval', 20)),
            enable_counterbalancing=bool(data.get('enable_counterbalancing', True)),
            instructions=data.get('instructions'),
            completion_message=data.get('completion_message'),
            status=data.get('status', 'draft'),
            experiment_metadata=data.get('experiment_metadata', {}) or {}
        )

        db.session.add(exp)
        db.session.commit()

        # Create per-experiment folder + settings db (and store paths into metadata)
        _exp_paths(exp)

        return jsonify({'success': True, 'experiment': exp.to_dict(include_stimuli=False)}), 201

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating experiment: {e}")
        return jsonify({'error': str(e)}), 500

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

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
def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

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

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/api/experiments/<experiment_id>/stimuli', methods=['POST'])
@require_auth
@require_roles(['admin', 'researcher'])
def upload_stimulus(experiment_id):
    """
    Upload stimulus for experiment.
    IMPORTANT: This endpoint is used by the current frontend, so it MUST save into:
      - per-experiment folder: experiments_data/<experimentName>/stimuli/
      - per-experiment settings DB: <experimentName>_Setting.db (table: stimuli)
    """
    try:
        # Check experiment exists
        experiment = Experiment.query.filter_by(experiment_id=experiment_id).first()
        if not experiment:
            return jsonify({'error': 'Experiment not found'}), 404

        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if not file or file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        filename = secure_filename(file.filename)
        if '.' not in filename or filename.rsplit('.', 1)[1].lower() not in ALLOWED_EXTENSIONS:
            return jsonify({'error': f'Invalid file type. Allowed: {sorted(ALLOWED_EXTENSIONS)}'}), 400

        # Ensure experiment folder + settings DB exists
        storage = experiment.experiment_metadata.get("exp_storage") if experiment.experiment_metadata else None
        if not storage:
            storage = _exp_paths(experiment)

        stimuli_dir = storage["stimuli_dir"]
        os.makedirs(stimuli_dir, exist_ok=True)

        # Save into experiment stimuli folder
        stimulus_id = str(uuid.uuid4())
        ext = filename.rsplit('.', 1)[1].lower()
        disk_name = f"{stimulus_id}.{ext}"
        file_path = os.path.join(stimuli_dir, disk_name)
        file.save(file_path)

        # Optional fields
        display_order = request.form.get('display_order')
        try:
            display_order = int(display_order) if display_order is not None and str(display_order).strip() != '' else 0
        except ValueError:
            display_order = 0
        label = request.form.get('label')

        # Insert into settings DB
        settings_db = _get_settings_db_path(experiment)
        con = _connect_sqlite(settings_db)
        try:
            con.execute(
                """
                INSERT INTO stimuli(stimulus_id, filename, file_path, mime_type, display_order, label, tags_json, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stimulus_id,
                    filename,
                    file_path,
                    f"image/{ext}" if ext != "gif" else "image/gif",
                    display_order,
                    label,
                    "[]",
                    "{}",
                    datetime.utcnow().isoformat()
                )
            )
            con.commit()
        finally:
            con.close()

        return jsonify({
            'success': True,
            'stimulus': {
                'stimulus_id': stimulus_id,
                'filename': filename,
                'display_order': display_order,
                'label': label,
                'url': f"/uploads/{disk_name}"
            }
        }), 201

    except Exception as e:
        logger.error(f"Error uploading stimulus: {e}")
        return jsonify({'error': str(e)}), 500
def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    """Serve uploaded stimulus files from experiment folders."""
    # 1) Backward-compatible: old global folder
    upload_folder = app.config.get('UPLOAD_FOLDER')
    if upload_folder and os.path.exists(os.path.join(upload_folder, filename)):
        return send_from_directory(upload_folder, filename)

    # 2) New: search experiment stimuli directories
    data_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'experiments_data'))
    if os.path.isdir(data_root):
        for root, dirs, files in os.walk(data_root):
            if os.path.basename(root) == "stimuli" and filename in files:
                return send_from_directory(root, filename)

    return jsonify({'error': 'File not found'}), 404

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

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
        # Validate experiment is ready
        # NOTE: stimuli live in the per-experiment settings DB, not the core Stimulus table.
        settings_db = _get_settings_db_path(experiment)
        stimuli_rows = _list_stimuli_from_settings(settings_db)
        if len(stimuli_rows) < 3:
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

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/api/sessions', methods=['POST'])
@limiter.limit(SESSIONS_RATE)
def create_session():
    """Create new subject session (creates a per-participant results DB: experimentName_Result_subjectId.db)."""
    try:
        data = request.get_json() or {}
        experiment_id = data.get('experiment_id')
        if not experiment_id:
            return jsonify({'error': 'experiment_id required'}), 400

        experiment = Experiment.query.filter_by(experiment_id=experiment_id).first()
        if not experiment:
            return jsonify({'error': 'Experiment not found'}), 404
        if experiment.status != 'active':
            return jsonify({'error': 'Experiment not active'}), 400

        # Ensure experiment storage exists
        storage = experiment.experiment_metadata.get("exp_storage") if experiment.experiment_metadata else None
        if not storage:
            storage = _exp_paths(experiment)

        subject_id = data.get('subject_id')  # optional
        # session_token encodes experiment_id so /next and /choice can find the right settings DB
        session_token = f"{experiment_id}_{uuid.uuid4().hex}"

        result_db_path = _participant_result_db_path(experiment, subject_id or "", session_token)
        init_participant_results_db(result_db_path)

        created_at = datetime.utcnow().isoformat()
        trials_total = int(experiment.max_trials)

        subject_meta = data.get('subject_metadata', {}) or {}
        subject_name = subject_meta.get('subject_name')

        # Insert session row
        con = _connect_sqlite(result_db_path)
        try:
            con.execute(
                """
                INSERT OR REPLACE INTO sessions(
                    session_token, experiment_id, subject_id, status, created_at, trials_total, trials_completed, current_trial,
                    subject_metadata_json, browser_info_json, ip_address
                ) VALUES (?, ?, ?, 'active', ?, ?, 0, 0, ?, ?, ?)
                """,
                (
                    session_token, experiment_id, subject_id,
                    created_at, trials_total,
                    json.dumps(subject_meta),
                    json.dumps(data.get('browser_info', {}) or {}),
                    request.remote_addr
                )
            )

            # Determine number of stimuli from SETTINGS DB (preferred) fallback to experiment.num_stimuli
            settings_db = storage["settings_db"]
            stim_rows = _list_stimuli_from_settings(settings_db)
            n_stimuli = len(stim_rows) if len(stim_rows) >= 2 else int(experiment.num_stimuli)

            # Initialize algorithm state
            mu = np.zeros(n_stimuli)
            sigma = np.eye(n_stimuli) * float(experiment.prior_variance)
            comparison_matrix = np.zeros((n_stimuli, n_stimuli))

            con.execute(
                """
                INSERT OR REPLACE INTO algorithm_state(
                    session_token, mu, sigma, comparison_matrix, trials_completed, total_trials, state_checksum, updated_at
                ) VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    session_token,
                    serialize_numpy(mu),
                    serialize_numpy(sigma),
                    serialize_numpy(comparison_matrix),
                    trials_total,
                    hashlib.sha256(mu.tobytes() + sigma.tobytes()).hexdigest(),
                    created_at
                )
            )
            con.commit()
        finally:
            con.close()

        # Index session_token -> result_db_path inside settings DB
        insert_session_index(
            storage["settings_db"], 
            session_token, 
            subject_id, 
            subject_name,  
            result_db_path, 
            created_at
        )

        return jsonify({
            'success': True,
            'session_token': session_token
        }), 201

    except Exception as e:
        logger.error(f"Error creating session: {e}")
        return jsonify({'error': str(e)}), 500

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/api/sessions/<session_token>/subject', methods=['PUT'])
@limiter.limit(SESSIONS_RATE)
def update_session_subject(session_token):
    """
    Update participant ID (subject_id) and/or subject_name for a session.
    Persists to:
      - per-participant results DB: sessions.subject_id + sessions.subject_metadata_json
      - per-experiment settings DB: session_index.subject_id + session_index.subject_name
    """
    try:
        data = request.get_json() or {}

        new_subject_id = (data.get("subject_id") or "").strip() or None
        new_subject_name = (data.get("subject_name") or "").strip() or None

        experiment, storage, result_db_path = _resolve_experiment_for_session(session_token)
        if not experiment or not storage or not result_db_path:
            return jsonify({'error': 'Session not found'}), 404

        settings_db = storage["settings_db"]


        # --- Update participant results DB ---
        con = _connect_sqlite(result_db_path)
        try:
            sess = con.execute("SELECT * FROM sessions WHERE session_token = ?", (session_token,)).fetchone()
            if not sess:
                return jsonify({'error': 'Session not found'}), 404

            subject_meta = json.loads(sess["subject_metadata_json"] or "{}")
            if new_subject_name is not None:
                subject_meta["subject_name"] = new_subject_name

            updated_subject_id = new_subject_id if new_subject_id is not None else sess["subject_id"]

            con.execute(
                "UPDATE sessions SET subject_id = ?, subject_metadata_json = ? WHERE session_token = ?",
                (updated_subject_id, json.dumps(subject_meta), session_token)
            )
            con.commit()
        finally:
            con.close()

        # --- Update experiment settings DB index ---
        scon = _connect_sqlite(settings_db)
        try:
            cols = [r["name"] for r in scon.execute("PRAGMA table_info(session_index)").fetchall()]
            if "subject_name" not in cols:
                scon.execute("ALTER TABLE session_index ADD COLUMN subject_name TEXT;")

            # If caller didn't send a field, keep existing
            row = scon.execute(
                "SELECT subject_id, subject_name FROM session_index WHERE session_token = ?",
                (session_token,)
            ).fetchone()
            if not row:
                return jsonify({'error': 'Session not found'}), 404

            final_subject_id = new_subject_id if new_subject_id is not None else row["subject_id"]
            final_subject_name = new_subject_name if new_subject_name is not None else row.get("subject_name")

            scon.execute(
                "UPDATE session_index SET subject_id = ?, subject_name = ? WHERE session_token = ?",
                (final_subject_id, final_subject_name, session_token)
            )
            scon.commit()
        finally:
            scon.close()

        return jsonify({
            "success": True,
            "session_token": session_token,
            "subject_id": final_subject_id,
            "subject_name": final_subject_name
        })

    except Exception as e:
        logger.error(f"Error updating session subject: {e}")
        return jsonify({'error': str(e)}), 500
    
def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/api/sessions/<session_token>/next', methods=['GET'])
@limiter.limit(NEXT_RATE)
def get_next_pair(session_token):
    """Get next stimulus pair for session using Bayesian algorithm (state stored in participant DB)."""
    try:
        # Parse experiment_id from token
        experiment, storage, result_db_path = _resolve_experiment_for_session(session_token)
        if not experiment or not storage or not result_db_path:
            return jsonify({'error': 'Session not found'}), 404


        # Load session + state
        con = _connect_sqlite(result_db_path)
        try:
            sess = con.execute("SELECT * FROM sessions WHERE session_token = ?", (session_token,)).fetchone()
            if not sess:
                return jsonify({'error': 'Session not found'}), 404

            if sess["status"] == "complete":
                return jsonify({'complete': True})

            trials_completed = int(sess["trials_completed"] or 0)
            trials_total = int(sess["trials_total"] or 0)
            current_trial = int(sess["current_trial"] or 0)

            if trials_completed >= trials_total:
                completed_at = datetime.utcnow().isoformat()
                con.execute(
                    "UPDATE sessions SET status='complete', completed_at=? WHERE session_token=?",
                    (completed_at, session_token)
                )
                con.commit()
                mark_session_complete(storage["settings_db"], session_token, completed_at)
                return jsonify({'complete': True})

            algo = con.execute("SELECT * FROM algorithm_state WHERE session_token = ?", (session_token,)).fetchone()
            if not algo:
                return jsonify({'error': 'Algorithm state not found'}), 500
        finally:
            con.close()

        # Load stimuli from settings DB
        stim_rows = _list_stimuli_from_settings(storage["settings_db"])
        if len(stim_rows) < 2:
            return jsonify({'error': 'Not enough stimuli'}), 400

        stimuli_list = [_stimulus_row_to_dict(r) for r in stim_rows]
        n_items = len(stimuli_list)

        # DEBUG: Write errors to a text file since there is no terminal
        try:
            from backend.bayesian_adaptive import BayesianPreferenceState, PureBayesianAdaptiveSelector
        except ImportError:
            try:
                from bayesian_adaptive import BayesianPreferenceState, PureBayesianAdaptiveSelector
            except Exception as e:
                # WRITE THE ERROR TO A FILE
                import traceback
                with open("error_log.txt", "w") as f:
                    f.write("--- CRASH REPORT ---\n")
                    f.write(f"Error: {str(e)}\n")
                    f.write(traceback.format_exc())
                
                # Still crash so the UI knows something is wrong
                return jsonify({'error': str(e)}), 500
        bayesian_state = BayesianPreferenceState(n_items)
        bayesian_state.mu = deserialize_numpy(algo["mu"], (n_items,))
        bayesian_state.Sigma = deserialize_numpy(algo["sigma"], (n_items, n_items))
        bayesian_state.comparison_matrix = deserialize_numpy(algo["comparison_matrix"], (n_items, n_items))

        selector = PureBayesianAdaptiveSelector(
            epsilon=float(experiment.epsilon),
            exploration_weight=float(experiment.exploration_weight)
        )

        i, j = selector.select_next_pair(bayesian_state)

        pair = [stimuli_list[i], stimuli_list[j]]

        pres_order = 'AB'
        if experiment.enable_counterbalancing and np.random.rand() > 0.5:
            pair = [pair[1], pair[0]]
            pres_order = 'BA'

        # Issue pair token (JWT)
        pair_token = jwt_issue_pair_token({
            'session_id': session_token,    # <--- ADD THIS LINE
            'session_token': session_token,
            'trial_number': current_trial + 1,
            'stimulus_a_id': str(pair[0]['stimulus_id']),
            'stimulus_b_id': str(pair[1]['stimulus_id']),
            'presentation_order': pres_order
        })

        return jsonify({
            'success': True,
            'trial_number': current_trial + 1,
            'stimulus_a': {
                'stimulus_id': pair[0]['stimulus_id'],
                'stimulus_name': pair[0].get('label') or pair[0].get('filename'),
                'filename': pair[0].get('filename'),
                'url': pair[0].get('url'),
                'mime_type': pair[0].get('mime_type'),
            },
            'stimulus_b': {
                'stimulus_id': pair[1]['stimulus_id'],
                'stimulus_name': pair[1].get('label') or pair[1].get('filename'),
                'filename': pair[1].get('filename'),
                'url': pair[1].get('url'),
                'mime_type': pair[1].get('mime_type'),
            },
            'presentation_order': pres_order,
            'pair_token': pair_token,
            'show_progress': bool(experiment.show_progress),
            'progress_percentage': (trials_completed / trials_total * 100) if trials_total > 0 else 0
        })

    except Exception as e:
        logger.error(f"Error getting next pair: {e}")
        return jsonify({'error': str(e)}), 500

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/api/sessions/<session_token>/choice', methods=['POST'])
@limiter.limit(CHOICE_RATE)
def record_choice(session_token):
    """Record subject's choice and update Bayesian beliefs (writes to participant DB)."""
    try:
        data = request.get_json() or {}

        experiment, storage, result_db_path = _resolve_experiment_for_session(session_token)
        if not experiment or not storage or not result_db_path:
            return jsonify({'error': 'Session not found'}), 404


        # Validate pair token
        pair_token = data.get('pair_token')
        if not pair_token:
            return jsonify({'error': 'Missing pair_token'}), 400
        try:
            pt = jwt_decode_pair_token(pair_token)
        except Exception as e:
            return jsonify({'error': f'Invalid pair_token: {e}'}), 400

        if pt.get('session_token') != session_token:
            return jsonify({'error': 'pair_token/session mismatch'}), 400

        required = ['stimulus_a_id', 'stimulus_b_id', 'chosen_stimulus_id', 'response_time_ms']
        for field in required:
            if field not in data:
                return jsonify({'error': f'Missing field: {field}'}), 400

        # Load stimuli list (sorted) to map ids -> indices
        stim_rows = _list_stimuli_from_settings(storage["settings_db"])
        if len(stim_rows) < 2:
            return jsonify({'error': 'Not enough stimuli'}), 400
        stimuli_list = [_stimulus_row_to_dict(r) for r in stim_rows]

        id_to_idx = {str(s['stimulus_id']): i for i, s in enumerate(stimuli_list)}
        stimulus_a_idx = id_to_idx.get(str(data['stimulus_a_id']))
        stimulus_b_idx = id_to_idx.get(str(data['stimulus_b_id']))
        winner_idx = id_to_idx.get(str(data['chosen_stimulus_id']))

        if stimulus_a_idx is None or stimulus_b_idx is None or winner_idx is None:
            return jsonify({'error': 'Invalid stimulus IDs'}), 400

        # Load session + algo state
        con = _connect_sqlite(result_db_path)
        try:
            sess = con.execute("SELECT * FROM sessions WHERE session_token = ?", (session_token,)).fetchone()
            if not sess:
                return jsonify({'error': 'Session not found'}), 404

            current_trial = int(sess["current_trial"] or 0)
            expected_trial = current_trial + 1
            if int(pt.get('trial_number') or 0) != expected_trial:
                return jsonify({'error': 'pair_token/session mismatch'}), 400

            algo = con.execute("SELECT * FROM algorithm_state WHERE session_token = ?", (session_token,)).fetchone()
            if not algo:
                return jsonify({'error': 'Algorithm state not found'}), 500

            # Try importing from backend folder, otherwise try local folder
            try:
                from backend.bayesian_adaptive import BayesianPreferenceState, PureBayesianAdaptiveSelector
            except ImportError:
                try:
                    from bayesian_adaptive import BayesianPreferenceState, PureBayesianAdaptiveSelector
                except ImportError:
                    # Last resort: try adding current directory to path
                    import sys
                    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
                    from backend.bayesian_adaptive import BayesianPreferenceState, PureBayesianAdaptiveSelector

            n_items = len(stimuli_list)
            bayesian_state = BayesianPreferenceState(n_items)
            bayesian_state.mu = deserialize_numpy(algo["mu"], (n_items,))
            bayesian_state.Sigma = deserialize_numpy(algo["sigma"], (n_items, n_items))
            bayesian_state.comparison_matrix = deserialize_numpy(algo["comparison_matrix"], (n_items, n_items))

            selector = PureBayesianAdaptiveSelector(
                epsilon=float(experiment.epsilon),
                exploration_weight=float(experiment.exploration_weight)
            )

            bayesian_state = selector.update_beliefs(
                bayesian_state,
                stimulus_a_idx,
                stimulus_b_idx,
                winner_idx
            )

            # Save updated state
            new_trials_completed = int(algo["trials_completed"] or 0) + 1
            updated_at = datetime.utcnow().isoformat()
            checksum = hashlib.sha256(bayesian_state.mu.tobytes() + bayesian_state.Sigma.tobytes()).hexdigest()

            con.execute(
                """
                UPDATE algorithm_state
                   SET mu=?, sigma=?, comparison_matrix=?, trials_completed=?, state_checksum=?, updated_at=?
                 WHERE session_token=?
                """,
                (
                    serialize_numpy(bayesian_state.mu),
                    serialize_numpy(bayesian_state.Sigma),
                    serialize_numpy(bayesian_state.comparison_matrix),
                    new_trials_completed,
                    checksum,
                    updated_at,
                    session_token
                )
            )

            # Insert choice row
            con.execute(
                """
                INSERT INTO choices(
                    session_token, trial_number, stimulus_a_id, stimulus_b_id, chosen_stimulus_id,
                    response_time_ms, timestamp, presentation_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_token,
                    expected_trial,
                    str(data['stimulus_a_id']),
                    str(data['stimulus_b_id']),
                    str(data['chosen_stimulus_id']),
                    int(data['response_time_ms']),
                    updated_at,
                    pt.get('presentation_order')
                )
            )

            # Update session counters
            trials_total = int(sess["trials_total"] or 0)
            trials_completed = int(sess["trials_completed"] or 0) + 1
            new_status = "active"
            completed_at = None

            # Completion conditions
            if selector.check_convergence(bayesian_state, float(experiment.convergence_threshold)):
                new_status = "complete"
                completed_at = updated_at
            elif trials_completed >= trials_total:
                new_status = "complete"
                completed_at = updated_at

            con.execute(
                """
                UPDATE sessions
                   SET trials_completed=?, current_trial=?, status=?,
                       completed_at=COALESCE(?, completed_at)
                 WHERE session_token=?
                """,
                (trials_completed, expected_trial, new_status, completed_at, session_token)
            )

            con.commit()

        finally:
            con.close()

        if completed_at:
            mark_session_complete(storage["settings_db"], session_token, completed_at)

        return jsonify({'success': True, 'complete': bool(completed_at)})

    except Exception as e:
        logger.error(f"Error recording choice: {e}")
        return jsonify({'error': str(e)}), 500

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/api/experiments/<experiment_id>/results', methods=['GET'])
@require_auth
@require_roles(['admin', 'researcher'])
def get_results(experiment_id):
    """Get experiment results (sessions are stored in per-participant DB files)."""
    try:
        experiment = Experiment.query.filter_by(experiment_id=experiment_id).first()
        if not experiment:
            return jsonify({'error': 'Experiment not found'}), 404

        storage = experiment.experiment_metadata.get("exp_storage") if experiment.experiment_metadata else None
        if not storage:
            storage = _exp_paths(experiment)

        # Read session_index from settings DB
        con = _connect_sqlite(storage["settings_db"])
        try:
            idx_rows = con.execute(
                "SELECT * FROM session_index ORDER BY created_at DESC"
            ).fetchall()
            idx_rows = [dict(r) for r in idx_rows]
        finally:
            con.close()

        sessions_out = []
        total_choices = 0
        total_rt = 0
        completed_sessions = 0
        active_sessions = 0

        for r in idx_rows:
            db_path = r.get("result_db_path")
            if not db_path or not os.path.exists(db_path):
                continue
            c2 = _connect_sqlite(db_path)
            try:
                sess = c2.execute("SELECT * FROM sessions WHERE session_token = ?", (r["session_token"],)).fetchone()
                if not sess:
                    continue
                sess = dict(sess)

                # count choices for this session
                n_choices = c2.execute(
                    "SELECT COUNT(*) AS n FROM choices WHERE session_token = ?",
                    (r["session_token"],)
                ).fetchone()["n"]
                total_choices += int(n_choices or 0)

                rt_sum = c2.execute(
                    "SELECT SUM(response_time_ms) AS s FROM choices WHERE session_token = ?",
                    (r["session_token"],)
                ).fetchone()["s"]
                if rt_sum:
                    total_rt += int(rt_sum)

                status = sess.get("status") or "active"
                if status == "complete":
                    completed_sessions += 1
                else:
                    active_sessions += 1
                sessions_out.append({
                    "session_id": sess["session_token"],
                    "session_token": sess["session_token"],
                    "subject_id": sess.get("subject_id"),
                    
                    # --- FIX: Read subject_name from the session index row (r) ---
                    "subject_name": r.get("subject_name"), 
                    
                    "participant_id": sess.get("subject_id"),
                    "status": status,
                    "created_at": sess.get("created_at"),
                    "completed_at": sess.get("completed_at"),
                    "trials_total": sess.get("trials_total"),
                    "trials_completed": sess.get("trials_completed"),
                })

            finally:
                c2.close()

        avg_rt = (total_rt / total_choices) if total_choices > 0 else 0

        results = {
            "experiment": experiment.to_dict(include_stimuli=False),
            "summary": {
                "total_sessions": len(sessions_out),
                "completed_sessions": completed_sessions,
                "active_sessions": active_sessions,
                "total_choices": total_choices,
                "avg_response_time_ms": avg_rt
            },
            "sessions": sessions_out
        }

        return jsonify(results)

    except Exception as e:
        logger.error(f"Error getting results: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/experiments/all', methods=['GET'])
@require_auth
@require_roles(['admin', 'researcher'])
def get_all_experiments():
    """Get all experiments for the admin dashboard (core DB + session counts from file system)."""
    try:
        experiments = Experiment.query \
            .filter(Experiment.archived_at.is_(None)) \
            .order_by(Experiment.created_at.desc()) \
            .all()

        results = []
        for exp in experiments:
            exp_data = exp.to_dict()
            
            # --- FIX: Count sessions by counting .db files in participants folder ---
            count = 0
            try:
                # 1. Resolve Storage Paths
                storage = exp.experiment_metadata.get("exp_storage")
                if not storage:
                    storage = _exp_paths(exp) # Ensure path exists
                
                participants_dir = storage.get("participants_dir")
                
                # 2. Count .db files in the participants directory
                if participants_dir and os.path.exists(participants_dir):
                    # List all files ending in .db (excluding temporary/journal files like .db-wal)
                    files = [f for f in os.listdir(participants_dir) if f.endswith('.db')]
                    count = len(files)

            except Exception as e:
                # Log error but allow dashboard to load with 0 count
                logger.warning(f"Could not count session files for experiment {exp.name}: {e}")
            
            exp_data['session_count'] = count
            results.append(exp_data)

        return jsonify({'success': True, 'experiments': results})
    except Exception as e:
        logger.error(f"Error getting all experiments: {e}")
        return jsonify({'error': str(e)}), 500

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/api/experiments/<experiment_id>/export_choices_csv', methods=['GET'])
@require_auth
@require_roles(['admin', 'researcher'])
def export_choices_csv(experiment_id):
    """Export ALL choices for an experiment as a CSV file (aggregated across participant DBs)."""
    try:
        experiment = Experiment.query.filter_by(experiment_id=experiment_id).first()
        if not experiment:
            return jsonify({'error': 'Experiment not found'}), 404

        storage = experiment.experiment_metadata.get("exp_storage") if experiment.experiment_metadata else None
        if not storage:
            storage = _exp_paths(experiment)

        # Load session index
        con = _connect_sqlite(storage["settings_db"])
        try:
            idx_rows = con.execute("SELECT * FROM session_index ORDER BY created_at ASC").fetchall()
            idx_rows = [dict(r) for r in idx_rows]
        finally:
            con.close()

        if not idx_rows:
            return jsonify({'error': 'No sessions found for this experiment'}), 404

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            'session_token', 'subject_id', 'trial_number',
            'stimulus_a_id', 'stimulus_b_id', 'chosen_stimulus_id',
            'response_time_ms', 'timestamp', 'presentation_order'
        ])

        wrote_any = False
        for r in idx_rows:
            db_path = r.get("result_db_path")
            if not db_path or not os.path.exists(db_path):
                continue
            c2 = _connect_sqlite(db_path)
            try:
                subj = r.get("subject_id")
                rows = c2.execute(
                    """
                    SELECT trial_number, stimulus_a_id, stimulus_b_id, chosen_stimulus_id,
                           response_time_ms, timestamp, presentation_order
                      FROM choices
                     WHERE session_token = ?
                     ORDER BY trial_number ASC
                    """,
                    (r["session_token"],)
                ).fetchall()
                for row in rows:
                    wrote_any = True
                    writer.writerow([
                        r["session_token"], subj,
                        row["trial_number"],
                        row["stimulus_a_id"], row["stimulus_b_id"], row["chosen_stimulus_id"],
                        row["response_time_ms"], row["timestamp"], row["presentation_order"]
                    ])
            finally:
                c2.close()

        if not wrote_any:
            return jsonify({'error': 'No choices found for this experiment'}), 404

        csv_bytes = output.getvalue().encode('utf-8')
        output.close()

        filename = f"{slugify(experiment.name)}_all_results_raw.csv"
        return Response(
            csv_bytes,
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'}
        )

    except Exception as e:
        logger.error(f"Error exporting CSV: {e}")
        return jsonify({'error': str(e)}), 500

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/api/experiments/<experiment_id>/export_clean_choices_csv', methods=['GET'])
@require_auth
@require_roles(['admin', 'researcher'])
def export_clean_choices_csv(experiment_id):
    """Export ALL choices for an experiment as a cleaned CSV (human-readable session + stimulus labels)."""
    try:
        experiment = Experiment.query.filter_by(experiment_id=experiment_id).first()
        if not experiment:
            return jsonify({'error': 'Experiment not found'}), 404

        storage = experiment.experiment_metadata.get("exp_storage") if experiment.experiment_metadata else None
        if not storage:
            storage = _exp_paths(experiment)

        # session ordering
        con = _connect_sqlite(storage["settings_db"])
        try:
            idx_rows = con.execute("SELECT * FROM session_index ORDER BY created_at ASC").fetchall()
            idx_rows = [dict(r) for r in idx_rows]
        finally:
            con.close()

        if not idx_rows:
            return jsonify({'error': 'No sessions found for this experiment'}), 404

        session_label = {r["session_token"]: f"S{str(i+1).zfill(3)}" for i, r in enumerate(idx_rows)}

        # stimuli map
        stim_rows = _list_stimuli_from_settings(storage["settings_db"])
        stim_map = {}
        for s in stim_rows:
            sid = str(s["stimulus_id"])
            label = s.get("label") or s.get("filename") or sid
            stim_map[sid] = label

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'session', 'subject_id', 'trial_number',
            'stimulus_a', 'stimulus_b', 'chosen_stimulus',
            'response_time_ms', 'timestamp', 'presentation_order'
        ])

        wrote_any = False
        for r in idx_rows:
            db_path = r.get("result_db_path")
            if not db_path or not os.path.exists(db_path):
                continue
            c2 = _connect_sqlite(db_path)
            try:
                subj = r.get("subject_id")
                rows = c2.execute(
                    """
                    SELECT trial_number, stimulus_a_id, stimulus_b_id, chosen_stimulus_id,
                           response_time_ms, timestamp, presentation_order
                      FROM choices
                     WHERE session_token = ?
                     ORDER BY trial_number ASC
                    """,
                    (r["session_token"],)
                ).fetchall()
                for row in rows:
                    wrote_any = True
                    writer.writerow([
                        session_label.get(r["session_token"], r["session_token"]),
                        subj,
                        row["trial_number"],
                        stim_map.get(row["stimulus_a_id"], row["stimulus_a_id"]),
                        stim_map.get(row["stimulus_b_id"], row["stimulus_b_id"]),
                        stim_map.get(row["chosen_stimulus_id"], row["chosen_stimulus_id"]),
                        row["response_time_ms"],
                        row["timestamp"],
                        row["presentation_order"]
                    ])
            finally:
                c2.close()

        if not wrote_any:
            return jsonify({'error': 'No choices found for this experiment'}), 404

        csv_bytes = output.getvalue().encode('utf-8')
        output.close()

        filename = f"{slugify(experiment.name)}_all_results_clean.csv"
        return Response(
            csv_bytes,
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'}
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

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/api/consent', methods=['GET'])
def get_consent():
    """Serve consent document."""
    try:
        return send_file(_current_consent_path())
    except Exception as e:
        logger.error(f"Consent serve error: {e}")
        return jsonify({'error': 'Consent not available'}), 404

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/api/debrief', methods=['GET'])
def get_debrief():
    """Serve debrief document."""
    try:
        return send_file(_current_debrief_path())
    except Exception as e:
        logger.error(f"Debrief serve error: {e}")
        return jsonify({'error': 'Debrief not available'}), 404

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

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

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

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

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/api/experiments/<experiment_id>/participants/<subject_id>/export_choices_csv', methods=['GET'])
@require_auth
@require_roles(['admin', 'researcher'])
def export_participant_choices_csv(experiment_id, subject_id):
    """Export choices for ONE participant as raw CSV."""
    try:
        experiment = Experiment.query.filter_by(experiment_id=experiment_id).first()
        if not experiment:
            return jsonify({'error': 'Experiment not found'}), 404

        storage = experiment.experiment_metadata.get("exp_storage") if experiment.experiment_metadata else None
        if not storage:
            storage = _exp_paths(experiment)

        con = _connect_sqlite(storage["settings_db"])
        try:
            idx_rows = con.execute(
                "SELECT * FROM session_index WHERE subject_id = ? ORDER BY created_at ASC",
                (subject_id,)
            ).fetchall()
            idx_rows = [dict(r) for r in idx_rows]
        finally:
            con.close()

        if not idx_rows:
            return jsonify({'error': 'No sessions found for this participant'}), 404

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'session_token', 'subject_id', 'trial_number',
            'stimulus_a_id', 'stimulus_b_id', 'chosen_stimulus_id',
            'response_time_ms', 'timestamp', 'presentation_order'
        ])

        wrote_any = False
        for r in idx_rows:
            db_path = r.get("result_db_path")
            if not db_path or not os.path.exists(db_path):
                continue
            c2 = _connect_sqlite(db_path)
            try:
                rows = c2.execute(
                    'SELECT trial_number, stimulus_a_id, stimulus_b_id, chosen_stimulus_id, '
                    'response_time_ms, timestamp, presentation_order '
                    'FROM choices WHERE session_token = ? ORDER BY trial_number ASC',
                    (r["session_token"],)
                ).fetchall()
                for row in rows:
                    wrote_any = True
                    writer.writerow([
                        r["session_token"], subject_id,
                        row["trial_number"],
                        row["stimulus_a_id"], row["stimulus_b_id"], row["chosen_stimulus_id"],
                        row["response_time_ms"], row["timestamp"], row["presentation_order"]
                    ])
            finally:
                c2.close()

        if not wrote_any:
            return jsonify({'error': 'No choices found for this participant'}), 404

        csv_bytes = output.getvalue().encode('utf-8')
        output.close()

        safe_subj = re.sub(r'[^a-zA-Z0-9_-]+','_',subject_id)
        filename = f"{slugify(experiment.name)}_{safe_subj}_raw.csv"
        return Response(csv_bytes, mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename="{filename}"'})
    except Exception as e:
        logger.error(f"Error exporting participant CSV: {e}")
        return jsonify({'error': str(e)}), 500

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/api/experiments/<experiment_id>/participants/<subject_id>/export_clean_choices_csv', methods=['GET'])
@require_auth
@require_roles(['admin', 'researcher'])
def export_participant_clean_choices_csv(experiment_id, subject_id):
    """Export choices for ONE participant as cleaned CSV (stimulus labels)."""
    try:
        experiment = Experiment.query.filter_by(experiment_id=experiment_id).first()
        if not experiment:
            return jsonify({'error': 'Experiment not found'}), 404

        storage = experiment.experiment_metadata.get("exp_storage") if experiment.experiment_metadata else None
        if not storage:
            storage = _exp_paths(experiment)

        con = _connect_sqlite(storage["settings_db"])
        try:
            idx_rows = con.execute(
                "SELECT * FROM session_index WHERE subject_id = ? ORDER BY created_at ASC",
                (subject_id,)
            ).fetchall()
            idx_rows = [dict(r) for r in idx_rows]
        finally:
            con.close()

        if not idx_rows:
            return jsonify({'error': 'No sessions found for this participant'}), 404

        # stimuli map
        stim_rows = _list_stimuli_from_settings(storage["settings_db"])
        stim_map = {}
        for s in stim_rows:
            sid = str(s["stimulus_id"])
            label = s.get("label") or s.get("filename") or sid
            stim_map[sid] = label

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'session', 'subject_id', 'trial_number',
            'stimulus_a', 'stimulus_b', 'chosen_stimulus',
            'response_time_ms', 'timestamp', 'presentation_order'
        ])

        wrote_any = False
        for idx, r in enumerate(idx_rows):
            db_path = r.get("result_db_path")
            if not db_path or not os.path.exists(db_path):
                continue
            session_label = f"S{str(idx+1).zfill(3)}"
            c2 = _connect_sqlite(db_path)
            try:
                rows = c2.execute(
                    'SELECT trial_number, stimulus_a_id, stimulus_b_id, chosen_stimulus_id, '
                    'response_time_ms, timestamp, presentation_order '
                    'FROM choices WHERE session_token = ? ORDER BY trial_number ASC',
                    (r["session_token"],)
                ).fetchall()
                for row in rows:
                    wrote_any = True
                    writer.writerow([
                        session_label,
                        subject_id,
                        row["trial_number"],
                        stim_map.get(row["stimulus_a_id"], row["stimulus_a_id"]),
                        stim_map.get(row["stimulus_b_id"], row["stimulus_b_id"]),
                        stim_map.get(row["chosen_stimulus_id"], row["chosen_stimulus_id"]),
                        row["response_time_ms"],
                        row["timestamp"],
                        row["presentation_order"]
                    ])
            finally:
                c2.close()

        if not wrote_any:
            return jsonify({'error': 'No choices found for this participant'}), 404

        csv_bytes = output.getvalue().encode('utf-8')
        output.close()

        safe_subj = re.sub(r'[^a-zA-Z0-9_-]+','_',subject_id)
        filename = f"{slugify(experiment.name)}_{safe_subj}_clean.csv"
        return Response(csv_bytes, mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename="{filename}"'})
    except Exception as e:
        logger.error(f"Error exporting participant clean CSV: {e}")
        return jsonify({'error': str(e)}), 500

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
# --- ADD THIS TO SERVE FRONTEND FILES ---
def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/frontend/<path:filename>')
def serve_frontend(filename):
    """Serves files from the frontend directory so the app works offline."""
    frontend_dir = os.path.join(os.path.dirname(app.root_path), 'frontend')
    return send_from_directory(frontend_dir, filename)

def _resolve_experiment_for_session(session_token: str):
    """
    Resolve (experiment, storage, result_db_path) for a session_token.

    Fast path:
      - try parsing experiment_id from token prefix, but VALIDATE that the token exists in that experiment's session_index

    Slow path:
      - scan all experiments and find the one whose settings DB session_index contains this token

    This fixes failures when experiment_id contains underscores.
    """
    # ---- Fast path: prefix parse + validate ----
    if "_" in session_token:
        candidate_id = session_token.split("_", 1)[0]
        exp = Experiment.query.filter_by(experiment_id=candidate_id).first()
        if exp:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            try:
                result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
                if result_db_path and os.path.exists(result_db_path):
                    return exp, storage, result_db_path
            except Exception:
                pass

    # ---- Slow path: scan all experiments ----
    for exp in Experiment.query.all():
        try:
            storage = exp.experiment_metadata.get("exp_storage") if exp.experiment_metadata else None
            if not storage:
                storage = _exp_paths(exp)

            result_db_path = lookup_result_db_for_session(storage["settings_db"], session_token)
            if result_db_path and os.path.exists(result_db_path):
                return exp, storage, result_db_path
        except Exception:
            continue

    return None, None, None

@app.route('/')
def index():
    """Redirects the base URL to the login page first for security."""
    # Change from 'experimenter_dashboard_improved.html' to your login file
    return serve_frontend('admin_PATCHED.html')
# ----------------------------------------
if __name__ == '__main__':
    # Automatically create the offline core database file and tables on click
    with app.app_context():
        # Core tables (users + experiments registry)
        db.create_all()
        print("SUCCESS: Core DB Initialized at:", app.config['SQLALCHEMY_DATABASE_URI'])


    
    app.run(
        host='127.0.0.1', # Use local loopback for offline security
        port=5000,
        debug=os.environ.get('FLASK_ENV') == 'development'
    )