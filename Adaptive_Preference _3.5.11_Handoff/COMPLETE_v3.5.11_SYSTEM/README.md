# COMPLETE ADAPTIVE PREFERENCE TESTING SYSTEM v3.5.7

**Status**: Production-Ready with GUI/A11Y/Beauty Patches Applied  
**Date**: November 9, 2025  
**WCAG Compliance**: 2.2 Level AA ✅

## 🎯 THIS IS THE COMPLETE SYSTEM

This package includes EVERYTHING you need:

### Backend (3 files)
- `backend/api.py` - Flask API server (940 lines)
- `backend/bayesian_adaptive.py` - Core Bayesian algorithm (497 lines)
- `backend/auth.py` - Authentication module

### Frontend (4 files - PATCHED)
- `frontend/subject_interface_complete_PATCHED.html` - Subject view with offline support
- `frontend/experimenter_dashboard_improved_PATCHED.html` - Experimenter GUI with help
- `frontend/admin_PATCHED.html` - Admin dashboard with keyboard shortcuts
- `frontend/results_dashboard_PATCHED.html` - Results/analytics with enhanced export

### Database
- `database/schema.sql` - Complete PostgreSQL schema (573 lines)

### Tests
- `tests/conftest.py` - Test configuration
- `tests/test_consent_endpoint.py` - Consent tests
- `tests/test_csv_contract.py` - CSV export tests

### Documentation
- `README.md` - This file
- `DEPLOYMENT_GUIDE.md` - Full deployment instructions
- `GUI_A11Y_PATCHES_DELIVERY.md` - Comprehensive patch documentation
- `QUICK_REFERENCE_v3.5.7.md` - Quick start guide
- `VERSION.txt` - Version info
- `CHANGELOG_v3.3.0.md` - Change history

### Tools
- `apply_patches.py` - Reusable patch automation script

## 🚀 QUICK START

### 1. Setup Database
```bash
createdb adaptive_preference
psql -d adaptive_preference -f database/schema.sql
```

### 2. Install Dependencies
```bash
pip install flask flask-sqlalchemy psycopg2-binary numpy scipy Pillow
```

### 3. Configure Environment
```bash
export DATABASE_URL="postgresql://localhost/adaptive_preference"
export SECRET_KEY="your-secret-key-here"
```

### 4. Start Backend
```bash
python backend/api.py
# Server runs on http://localhost:5000
```

### 5. Open Frontend
```bash
# Experimenter interface
open frontend/experimenter_dashboard_improved_PATCHED.html

# Admin interface
open frontend/admin_PATCHED.html

# Subject interface (demo mode)
open frontend/subject_interface_complete_PATCHED.html?demo=true
```

## ✅ WHAT'S NEW IN v3.5.7

### WCAG 2.2 AA Compliance
- ✅ Focus indicators (3px outline + 6px shadow)
- ✅ Skip to main content link
- ✅ ARIA labels and live regions
- ✅ 4.5:1 contrast ratio minimum
- ✅ Full keyboard navigation

### Resilient Networking
- ✅ Toast notifications (visual + audio feedback)
- ✅ Exponential backoff retry (1s → 2s → 4s)
- ✅ Request queueing with localStorage
- ✅ Offline detection banner
- ✅ Automatic recovery on reconnect
- ✅ 10-second timeout protection

### Help System
- ✅ Contextual help modals
- ✅ Real-world examples
- ✅ Calculation helpers
- ✅ WCAG accessibility notes

### Admin QoL
- ✅ Keyboard shortcuts (Alt+N, Alt+H, etc.)
- ✅ Enhanced data export
- ✅ Progress feedback

## 📊 SYSTEM METRICS

- **Total Lines**: 5,784 lines of code
- **Backend**: 70KB (Python)
- **Frontend**: 143KB (HTML/JS/CSS)
- **Database**: 20KB (SQL)
- **Tests**: 2KB (Python)
- **Docs**: 50KB (Markdown)

## 🧪 TESTING

```bash
# Run tests (requires pytest)
pip install pytest pytest-flask
pytest tests/

# Manual testing
# 1. Create experiment
# 2. Test offline mode (disconnect internet)
# 3. Test keyboard navigation (Tab key)
# 4. Test screen reader (NVDA/JAWS)
```

## 📚 DOCUMENTATION

- **Full Guide**: See GUI_A11Y_PATCHES_DELIVERY.md
- **Quick Ref**: See QUICK_REFERENCE_v3.5.7.md
- **Deployment**: See DEPLOYMENT_GUIDE.md

## 🔧 TROUBLESHOOTING

**Backend won't start?**
- Check DATABASE_URL environment variable
- Ensure PostgreSQL is running

**Frontend not connecting?**
- Check API_BASE URL in HTML files
- Default is http://localhost:5000

**Toasts not showing?**
- Check browser console for errors
- Ensure JavaScript is enabled

## ⚠️ IMPORTANT NOTES

### Browser Support
- Chrome 90+, Firefox 88+, Safari 14+, Edge 90+
- IE11 NOT supported

### Production Deployment
Before deploying to production:
1. Change SECRET_KEY
2. Enable HTTPS
3. Configure authentication
4. Set up backups
5. Run security audit

## 📞 SUPPORT

For issues or questions:
1. Check QUICK_REFERENCE_v3.5.7.md
2. Review GUI_A11Y_PATCHES_DELIVERY.md
3. Run: `python apply_patches.py --help`

## ✅ VERIFICATION

To verify installation:
```bash
# Check all files present
ls backend/ database/ frontend/ tests/

# Verify backend
python -c "from backend.bayesian_adaptive import PureBayesianAdaptiveSelector; print('✓ Backend OK')"

# Verify database
psql -d adaptive_preference -c "SELECT COUNT(*) FROM pg_tables WHERE schemaname='public';"
# Should show 9 tables

# Test frontend
open frontend/subject_interface_complete_PATCHED.html?demo=true
# Should load without errors
```

## Governance & Installer

This system includes a Governance + Autoinstaller kit in this folder:

- `install.sh` – sets up a `.venv`, installs dependencies, and runs governance checks.
- `v3_governance.yml` – describes critical files and imports that must remain valid.
- `scripts/` – guard scripts that validate repository health (syntax, imports, hollow dirs, etc).

To set up on a new machine:

```bash
cd Adaptive_Preference_GUI/Adaptive_Preference\ _3.5.11_Handoff\ /COMPLETE_v3.5.11_SYSTEM
./install.sh


---

**This is the COMPLETE system - ready to deploy!**
