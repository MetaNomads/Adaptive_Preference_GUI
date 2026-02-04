"""
Filesystem + SQLite helpers for per-experiment settings DB and per-participant results DB.

Naming:
- Experiment settings DB: <experimentName>_Setting.db
- Participant results DB: <experimentName>_Result_<subjectId>.db

Stimuli are stored INSIDE the experiment folder so deleting the experiment folder removes stimuli.
"""

from __future__ import annotations

import os
import re
import sqlite3
from typing import Dict, Optional


def slugify(name: str, max_len: int = 64) -> str:
    """
    Convert experiment name to a safe filename slug.
    """
    name = (name or "").strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if not name:
        name = "experiment"
    return name[:max_len]


def get_data_root(base_dir: str) -> str:
    """
    base_dir should be backend folder. We store data at ../experiments_data
    """
    root = os.path.abspath(os.path.join(base_dir, "..", "experiments_data"))
    os.makedirs(root, exist_ok=True)
    return root


def get_experiment_paths(base_dir: str, experiment_id: str, experiment_name: str) -> Dict[str, str]:
    """
    Returns paths for experiment folder, settings DB, stimuli folder, participants folder.

    Folder name rule:
    - Use just the experiment name slug: experiments_data/<exp_slug>
    - If that folder already exists AND belongs to a different experiment_id,
      use a deterministic suffix: <exp_slug>_<experiment_id[:8]>

    We store a marker file ".experiment_id" inside the folder to know ownership.
    """
    data_root = get_data_root(base_dir)
    exp_slug = slugify(experiment_name)

    preferred_dir = os.path.join(data_root, exp_slug)
    marker_path = os.path.join(preferred_dir, ".experiment_id")

    exp_dir = preferred_dir

    if os.path.exists(preferred_dir):
        # If folder exists, check if it belongs to THIS experiment
        try:
            if os.path.exists(marker_path):
                existing_id = open(marker_path, "r", encoding="utf-8").read().strip()
                if existing_id != str(experiment_id):
                    exp_dir = os.path.join(data_root, f"{exp_slug}_{str(experiment_id)[:8]}")
            else:
                # No marker -> assume it's a legacy folder; avoid collisions deterministically
                exp_dir = os.path.join(data_root, f"{exp_slug}_{str(experiment_id)[:8]}")
        except Exception:
            exp_dir = os.path.join(data_root, f"{exp_slug}_{str(experiment_id)[:8]}")

    stimuli_dir = os.path.join(exp_dir, "stimuli")
    participants_dir = os.path.join(exp_dir, "participants")
    os.makedirs(stimuli_dir, exist_ok=True)
    os.makedirs(participants_dir, exist_ok=True)

    # Write ownership marker (safe even if already correct)
    try:
        os.makedirs(exp_dir, exist_ok=True)
        with open(os.path.join(exp_dir, ".experiment_id"), "w", encoding="utf-8") as f:
            f.write(str(experiment_id))
    except Exception:
        pass

    settings_db = os.path.join(exp_dir, f"{exp_slug}_Setting.db")

    return {
        "data_root": data_root,
        "exp_dir": exp_dir,
        "stimuli_dir": stimuli_dir,
        "participants_dir": participants_dir,
        "settings_db": settings_db,
        "exp_slug": exp_slug,
    }



def _connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con


def init_settings_db(settings_db_path: str) -> None:
    """
    Create tables for experiment settings DB if missing.
    """
    con = _connect(settings_db_path)
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS experiment_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS stimuli (
                stimulus_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                mime_type TEXT,
                display_order INTEGER DEFAULT 0,
                label TEXT,
                tags_json TEXT DEFAULT '[]',
                metadata_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS session_index (
                session_token TEXT PRIMARY KEY,
                subject_id TEXT,
                result_db_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            """
            
        )

        # ---- MIGRATION: add subject_name column if missing ----
        cols = [r["name"] for r in con.execute("PRAGMA table_info(session_index)").fetchall()]
        if "subject_name" not in cols:
            con.execute("ALTER TABLE session_index ADD COLUMN subject_name TEXT;")
        
        con.commit()
    finally:
        con.close()


def init_participant_results_db(results_db_path: str) -> None:
    """
    Create tables for per-participant results DB if missing.
    """
    con = _connect(results_db_path)
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_token TEXT PRIMARY KEY,
                experiment_id TEXT NOT NULL,
                subject_id TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                completed_at TEXT,
                trials_total INTEGER NOT NULL,
                trials_completed INTEGER NOT NULL DEFAULT 0,
                current_trial INTEGER NOT NULL DEFAULT 0,
                subject_metadata_json TEXT DEFAULT '{}',
                browser_info_json TEXT DEFAULT '{}',
                ip_address TEXT
            );

            CREATE TABLE IF NOT EXISTS algorithm_state (
                session_token TEXT PRIMARY KEY,
                mu BLOB NOT NULL,               -- CHANGED TO BLOB
                sigma BLOB NOT NULL,            -- CHANGED TO BLOB
                comparison_matrix BLOB NOT NULL,-- CHANGED TO BLOB
                trials_completed INTEGER NOT NULL DEFAULT 0,
                total_trials INTEGER NOT NULL,
                state_checksum TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS choices (
                choice_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_token TEXT NOT NULL,
                trial_number INTEGER NOT NULL,
                stimulus_a_id TEXT NOT NULL,
                stimulus_b_id TEXT NOT NULL,
                chosen_stimulus_id TEXT NOT NULL,
                response_time_ms INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                presentation_order TEXT,
                FOREIGN KEY(session_token) REFERENCES sessions(session_token) ON DELETE CASCADE
            );
            """
        )
        con.commit()
    finally:
        con.close()


def lookup_result_db_for_session(settings_db_path: str, session_token: str) -> Optional[str]:
    con = _connect(settings_db_path)
    try:
        row = con.execute(
            "SELECT result_db_path FROM session_index WHERE session_token = ?",
            (session_token,)
        ).fetchone()
        return row["result_db_path"] if row else None
    finally:
        con.close()


def insert_session_index(
    settings_db_path: str,
    session_token: str,
    subject_id: Optional[str],
    subject_name: Optional[str],
    result_db_path: str,
    created_at_iso: str
) -> None:

    con = _connect(settings_db_path)
    try:
        # Check if column exists, if not add it (Migration for older databases)
        cols = [r["name"] for r in con.execute("PRAGMA table_info(session_index)").fetchall()]
        if "subject_name" not in cols:
            con.execute("ALTER TABLE session_index ADD COLUMN subject_name TEXT;")

        # Now insert with subject_name
        con.execute(
            """
            INSERT OR REPLACE INTO session_index(session_token, subject_id, subject_name, result_db_path, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_token, subject_id, subject_name, result_db_path, created_at_iso)
        )
        con.commit()
    finally:
        con.close()

def mark_session_complete(settings_db_path: str, session_token: str, completed_at_iso: str) -> None:
    con = _connect(settings_db_path)
    try:
        con.execute(
            "UPDATE session_index SET completed_at = ? WHERE session_token = ?",
            (completed_at_iso, session_token)
        )
        con.commit()
    finally:
        con.close()
