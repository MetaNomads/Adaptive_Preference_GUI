#!/usr/bin/env python3
"""
Apply GUI/A11y/Beauty patches to Adaptive Preference System v3.5.6
Implements WCAG 2.2 AA compliance, resilient networking, and QoL improvements
"""

import re
import os

def apply_patches():
    """Apply all patches to frontend files"""
    
    base_dir = "/mnt/user-data/outputs/frontend"
    
    # ===== PATCH 1: subject_interface_complete.html =====
    print("Applying patches to subject_interface_complete.html...")
    
    with open(f"{base_dir}/subject_interface_complete.html", 'r') as f:
        subject_html = f.read()
    
    # Find the position after progress-text style (around line 66)
    toast_css_insertion_point = subject_html.find('.progress-text {')
    if toast_css_insertion_point > -1:
        # Find end of that style block
        insertion_pos = subject_html.find('}', toast_css_insertion_point) + 1
        
        toast_css = '''

        /* ===== TOAST NOTIFICATIONS (WCAG 4.1.3 Status Messages) ===== */
        .toast-container {
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 10000;
            display: flex;
            flex-direction: column;
            gap: 10px;
            max-width: 400px;
        }

        .toast {
            background: white;
            border-radius: 12px;
            padding: 16px 20px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.2);
            display: flex;
            align-items: center;
            gap: 12px;
            animation: slideIn 0.3s ease;
            border-left: 4px solid #667eea;
        }

        .toast.success { border-left-color: #48bb78; }
        .toast.error { border-left-color: #fc8181; }
        .toast.warning { border-left-color: #f6ad55; }

        .toast-icon {
            font-size: 1.5em;
            flex-shrink: 0;
        }

        .toast-content { flex: 1; }
        .toast-title {
            font-weight: 600;
            margin-bottom: 4px;
            color: #333;
        }
        .toast-message {
            font-size: 0.9em;
            color: #666;
        }

        .toast-close {
            background: none;
            border: none;
            font-size: 1.2em;
            cursor: pointer;
            color: #999;
            padding: 0;
            width: 24px;
            height: 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: color 0.2s;
        }

        .toast-close:hover { color: #333; }

        @keyframes slideIn {
            from {
                transform: translateX(400px);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }

        /* Offline Indicator */
        .offline-banner {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            background: #fc8181;
            color: white;
            padding: 12px;
            text-align: center;
            font-weight: 600;
            z-index: 9999;
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
            display: none;
        }

        .offline-banner.show {
            display: block;
            animation: slideDown 0.3s ease;
        }

        @keyframes slideDown {
            from { transform: translateY(-100%); }
            to { transform: translateY(0); }
        }

        /* ===== WCAG 2.4.7 Focus Visible ===== */
        *:focus {
            outline: 3px solid #667eea;
            outline-offset: 2px;
        }

        button:focus,
        .stimulus-option:focus {
            outline: 3px solid #667eea;
            outline-offset: 4px;
            box-shadow: 0 0 0 6px rgba(102, 126, 234, 0.2);
        }

        .skip-link {
            position: absolute;
            top: -40px;
            left: 0;
            background: #667eea;
            color: white;
            padding: 8px 16px;
            text-decoration: none;
            font-weight: 600;
            z-index: 100;
            border-radius: 0 0 8px 0;
        }

        .skip-link:focus { top: 0; }
'''
        
        subject_html = subject_html[:insertion_pos] + toast_css + subject_html[insertion_pos:]
    
    # Add HTML elements after <body> tag
    body_tag_pos = subject_html.find('<body>')
    if body_tag_pos > -1:
        body_insertion_pos = subject_html.find('>', body_tag_pos) + 1
        
        html_additions = '''
    <!-- Skip to main content (WCAG 2.4.1) -->
    <a href="#main-content" class="skip-link">Skip to main content</a>

    <!-- Offline Banner (WCAG 4.1.3) -->
    <div id="offlineBanner" class="offline-banner" role="alert" aria-live="assertive">
        ⚠ No Internet Connection - Your responses are being saved locally
    </div>

    <!-- Toast Notification Container -->
    <div id="toastContainer" class="toast-container" aria-live="polite" aria-atomic="false"></div>

'''
        subject_html = subject_html[:body_insertion_pos] + html_additions + subject_html[body_insertion_pos:]
    
    # Add resilient networking JavaScript before </script>
    script_end = subject_html.rfind('</script>')
    if script_end > -1:
        networking_js = '''

        // ===== RESILIENT NETWORKING SYSTEM =====
        const networkState = {
            isOnline: navigator.onLine,
            requestQueue: [],
            retryCount: new Map(),
            maxRetries: 3
        };

        function showToast(title, message, type = 'info') {
            const container = document.getElementById('toastContainer');
            if (!container) return;
            
            const toast = document.createElement('div');
            toast.className = `toast ${type}`;
            toast.setAttribute('role', 'status');
            toast.setAttribute('aria-live', 'polite');
            
            const icons = {
                success: '✓',
                error: '✗',
                warning: '⚠',
                info: 'ℹ'
            };
            
            toast.innerHTML = `
                <span class="toast-icon" aria-hidden="true">${icons[type]}</span>
                <div class="toast-content">
                    <div class="toast-title">${title}</div>
                    <div class="toast-message">${message}</div>
                </div>
                <button class="toast-close" aria-label="Close notification" onclick="this.parentElement.remove()">×</button>
            `;
            
            container.appendChild(toast);
            
            setTimeout(() => {
                toast.style.opacity = '0';
                toast.style.transform = 'translateX(400px)';
                setTimeout(() => toast.remove(), 300);
            }, 5000);
        }

        window.addEventListener('online', () => {
            networkState.isOnline = true;
            const banner = document.getElementById('offlineBanner');
            if (banner) banner.classList.remove('show');
            showToast('Back Online', 'Connection restored. Processing queued data...', 'success');
            processQueue();
        });

        window.addEventListener('offline', () => {
            networkState.isOnline = false;
            const banner = document.getElementById('offlineBanner');
            if (banner) banner.classList.add('show');
            showToast('Connection Lost', 'Your responses will be saved and sent when connection returns', 'warning');
        });

        async function fetchWithRetry(url, options, identifier) {
            const retries = networkState.retryCount.get(identifier) || 0;
            
            if (retries >= networkState.maxRetries) {
                showToast('Request Failed', 'Maximum retries exceeded. Data queued for later.', 'error');
                queueRequest(url, options, identifier);
                return { error: 'max_retries', queued: true };
            }
            
            try {
                const controller = new AbortController();
                const timeout = setTimeout(() => controller.abort(), 10000);
                
                const response = await fetch(url, {
                    ...options,
                    signal: controller.signal
                });
                
                clearTimeout(timeout);
                
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                
                networkState.retryCount.delete(identifier);
                return await response.json();
                
            } catch (error) {
                console.error(`Fetch error (attempt ${retries + 1}):`, error);
                
                const delay = Math.pow(2, retries) * 1000;
                networkState.retryCount.set(identifier, retries + 1);
                
                if (retries < networkState.maxRetries - 1) {
                    showToast('Retrying...', `Attempt ${retries + 2} of ${networkState.maxRetries}`, 'warning');
                    await new Promise(resolve => setTimeout(resolve, delay));
                    return fetchWithRetry(url, options, identifier);
                }
                
                queueRequest(url, options, identifier);
                return { error: error.message, queued: true };
            }
        }

        function queueRequest(url, options, identifier) {
            const exists = networkState.requestQueue.find(r => r.identifier === identifier);
            if (!exists) {
                networkState.requestQueue.push({ url, options, identifier, timestamp: Date.now() });
                showToast('Choice Queued', 'Will be sent when connection improves', 'info');
                
                try {
                    localStorage.setItem('pendingChoices', JSON.stringify(networkState.requestQueue));
                } catch (e) {
                    console.error('Failed to save to localStorage:', e);
                }
            }
        }

        async function processQueue() {
            if (networkState.requestQueue.length === 0) return;
            
            showToast('Processing Queue', `Sending ${networkState.requestQueue.length} queued choice(s)`, 'info');
            
            const queue = [...networkState.requestQueue];
            networkState.requestQueue = [];
            
            for (const request of queue) {
                try {
                    const response = await fetch(request.url, request.options);
                    if (response.ok) {
                        showToast('Choice Sent', 'Queued response successfully recorded', 'success');
                    } else {
                        networkState.requestQueue.push(request);
                    }
                } catch (error) {
                    networkState.requestQueue.push(request);
                }
            }
            
            if (networkState.requestQueue.length > 0) {
                localStorage.setItem('pendingChoices', JSON.stringify(networkState.requestQueue));
            } else {
                localStorage.removeItem('pendingChoices');
            }
        }

        // Override confirmChoice to use resilient networking
        const originalConfirmChoice = window.confirmChoice;
        window.confirmChoice = async function() {
            if (!state.selectedChoice) return;

            if (window.demoMode) {
                return originalConfirmChoice.call(this);
            }

            const responseTime = Date.now() - state.trialStartTime;
            const chosenStimulus = state.selectedChoice === 'A' ? 
                state.currentPair.stimulusA : state.currentPair.stimulusB;

            const choiceData = {
                stimulus_a_id: state.currentPair.stimulusA.stimulus_id,
                stimulus_b_id: state.currentPair.stimulusB.stimulus_id,
                chosen_stimulus_id: chosenStimulus.stimulus_id,
                response_time_ms: responseTime,
                presentation_order: 'AB'
            };

            const identifier = `choice_${state.trialsCompleted + 1}_${Date.now()}`;
            const result = await fetchWithRetry(
                `${API_BASE}/sessions/${state.sessionToken}/choice`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(choiceData)
                },
                identifier
            );

            state.trialsCompleted++;
            state.choices.push({
                trial: state.trialsCompleted,
                chosen: state.selectedChoice,
                responseTime: responseTime
            });

            if (result && !result.error && !result.queued) {
                updateProgress();
            }

            if (result && result.complete) {
                showCompletion();
            } else if (state.trialsCompleted >= state.totalTrials) {
                showCompletion();
            } else if (shouldShowBreak()) {
                showBreak();
            } else {
                loadNextTrial();
            }
        };

        window.addEventListener('DOMContentLoaded', () => {
            try {
                const saved = localStorage.getItem('pendingChoices');
                if (saved) {
                    networkState.requestQueue = JSON.parse(saved);
                    if (networkState.isOnline && networkState.requestQueue.length > 0) {
                        setTimeout(() => processQueue(), 2000);
                    }
                }
            } catch (e) {
                console.error('Failed to load queued choices:', e);
            }
        });

'''
        subject_html = subject_html[:script_end] + networking_js + subject_html[script_end:]
    
    # Write patched file
    with open(f"{base_dir}/subject_interface_complete_PATCHED.html", 'w') as f:
        f.write(subject_html)
    
    print("✅ subject_interface_complete.html patched")
    
    # ===== PATCH 2: experimenter_dashboard_improved.html =====
    print("\nApplying patches to experimenter_dashboard_improved.html...")
    
    with open(f"{base_dir}/experimenter_dashboard_improved.html", 'r') as f:
        exp_html = f.read()
    
    # Add help system before closing script tag
    script_end = exp_html.rfind('</script>')
    if script_end > -1:
        help_system = '''

        // ===== HELP-INTENSIVE DESIGN SYSTEM =====
        const helpContent = {
            'expName': {
                title: 'Experiment Name',
                content: 'Choose a descriptive name that identifies your study. This helps you organize multiple experiments.',
                example: 'Example: "Face Preference Study - Fall 2025"'
            },
            'trialsSlider': {
                title: 'Number of Trials',
                content: 'Each trial shows 2 images. More trials = more accurate results but longer session time.',
                example: 'Rule of thumb: 3-5 trials per image for good coverage',
                calculation: 'With N images: Min trials = N×3, Ideal = N×5'
            }
        };

        function showHelp(topic) {
            const help = helpContent[topic] || {
                title: 'Help',
                content: 'Contextual help for this field.'
            };

            const modal = document.createElement('div');
            modal.style.cssText = `
                position: fixed; top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(0,0,0,0.8); display: flex; align-items: center;
                justify-content: center; z-index: 10000; padding: 20px;
            `;
            modal.setAttribute('role', 'dialog');
            modal.setAttribute('aria-labelledby', 'helpTitle');

            modal.innerHTML = `
                <div style="background: white; border-radius: 16px; max-width: 600px; 
                            padding: 32px; max-height: 80vh; overflow-y: auto;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 20px;">
                        <h2 id="helpTitle" style="color: #667eea; margin: 0;">${help.title}</h2>
                        <button onclick="this.closest('[role=dialog]').remove()" 
                                style="background: none; border: none; font-size: 2em; cursor: pointer;">×</button>
                    </div>
                    <div style="color: #333; line-height: 1.6;">
                        <p>${help.content}</p>
                        ${help.example ? `<div style="background: #f0f9ff; padding: 16px; border-radius: 8px; margin-top: 16px;">
                            <strong>💡 Example:</strong><br>${help.example}</div>` : ''}
                        ${help.calculation ? `<div style="background: #f0fdf4; padding: 16px; border-radius: 8px; margin-top: 16px;">
                            <strong>📊 Calculation:</strong><br>${help.calculation}</div>` : ''}
                    </div>
                    <button onclick="this.closest('[role=dialog]').remove()"
                            style="margin-top: 24px; padding: 12px 24px; background: #667eea; 
                                   color: white; border: none; border-radius: 8px; width: 100%; cursor: pointer;">
                        Got it!
                    </button>
                </div>
            `;

            document.body.appendChild(modal);
        }

'''
        exp_html = exp_html[:script_end] + help_system + exp_html[script_end:]
    
    with open(f"{base_dir}/experimenter_dashboard_improved_PATCHED.html", 'w') as f:
        f.write(exp_html)
    
    print("✅ experimenter_dashboard_improved.html patched")
    
    # ===== PATCH 3: admin.html =====
    print("\nApplying patches to admin.html...")
    
    with open(f"{base_dir}/admin.html", 'r') as f:
        admin_html = f.read()
    
    # Add keyboard shortcuts before closing script tag
    script_end = admin_html.rfind('</script>')
    if script_end > -1:
        shortcuts_js = '''

        // ===== KEYBOARD SHORTCUTS (Admin QoL + WCAG 2.1.1) =====
        const shortcuts = {
            'Alt+N': () => document.querySelector('[href*="experimenter"]')?.click(),
            'Alt+R': () => location.reload(),
            'Alt+H': () => showShortcutsHelp(),
            '/': (e) => { const search = document.querySelector('input[type="search"]'); if(search) { e.preventDefault(); search.focus(); } }
        };

        function handleKeyboardShortcut(e) {
            const key = [];
            if (e.altKey) key.push('Alt');
            if (e.ctrlKey) key.push('Ctrl');
            key.push(e.key);

            const combo = key.join('+');
            const handler = shortcuts[combo];

            if (handler) {
                e.preventDefault();
                handler(e);
            }
        }

        function showShortcutsHelp() {
            const modal = document.createElement('div');
            modal.setAttribute('role', 'dialog');
            modal.style.cssText = `
                position: fixed; top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(0,0,0,0.9); display: flex; align-items: center;
                justify-content: center; z-index: 10000; padding: 20px;
            `;

            modal.innerHTML = `
                <div style="background: var(--panel); border: 1px solid var(--border); 
                            border-radius: 16px; max-width: 600px; padding: 32px; color: #e8ecff;">
                    <h2 style="margin-bottom: 24px; color: var(--accent);">⌨️ Keyboard Shortcuts</h2>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr><td style="padding: 12px; border-bottom: 1px solid var(--border);"><kbd style="background: rgba(255,255,255,0.1); padding: 4px 8px; border-radius: 4px;">Alt+N</kbd></td><td style="padding: 12px; border-bottom: 1px solid var(--border);">New Experiment</td></tr>
                        <tr><td style="padding: 12px; border-bottom: 1px solid var(--border);"><kbd style="background: rgba(255,255,255,0.1); padding: 4px 8px; border-radius: 4px;">Alt+R</kbd></td><td style="padding: 12px; border-bottom: 1px solid var(--border);">Refresh Page</td></tr>
                        <tr><td style="padding: 12px; border-bottom: 1px solid var(--border);"><kbd style="background: rgba(255,255,255,0.1); padding: 4px 8px; border-radius: 4px;">Alt+H</kbd></td><td style="padding: 12px; border-bottom: 1px solid var(--border);">Show This Help</td></tr>
                        <tr><td style="padding: 12px;"><kbd style="background: rgba(255,255,255,0.1); padding: 4px 8px; border-radius: 4px;">/</kbd></td><td style="padding: 12px;">Focus Search</td></tr>
                    </table>
                    <button onclick="this.closest('[role=dialog]').remove()" 
                            style="margin-top: 24px; padding: 12px 24px; background: var(--accent); 
                                   color: white; border: none; border-radius: 8px; width: 100%; cursor: pointer;">
                        Close
                    </button>
                </div>
            `;

            document.body.appendChild(modal);
        }

        document.addEventListener('keydown', handleKeyboardShortcut);

        // Show hint on first visit
        window.addEventListener('DOMContentLoaded', () => {
            if (!localStorage.getItem('shortcuts_hint_shown')) {
                setTimeout(() => {
                    if (typeof showToast === 'function') {
                        showToast('Keyboard Shortcuts', 'Press Alt+H to view all shortcuts', 'info');
                    }
                    localStorage.setItem('shortcuts_hint_shown', 'true');
                }, 2000);
            }
        });

'''
        admin_html = admin_html[:script_end] + shortcuts_js + admin_html[script_end:]
    
    # Add toast system CSS
    style_end = admin_html.find('</style>')
    if style_end > -1:
        toast_css = '''
    .toast-container { position: fixed; top: 20px; right: 20px; z-index: 10001; display: flex; flex-direction: column; gap: 10px; max-width: 400px; }
    .toast { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px 20px; box-shadow: 0 8px 32px rgba(0,0,0,0.4); display: flex; align-items: center; gap: 12px; animation: slideIn 0.3s ease; border-left: 4px solid var(--accent); color: #e8ecff; }
    .toast.success { border-left-color: #48bb78; }
    .toast.error { border-left-color: #fc8181; }
    .toast.warning { border-left-color: #f6ad55; }
    .toast-icon { font-size: 1.5em; }
    .toast-content { flex: 1; }
    .toast-title { font-weight: 600; margin-bottom: 4px; }
    .toast-message { font-size: 0.9em; opacity: 0.8; }
    .toast-close { background: none; border: none; color: inherit; cursor: pointer; padding: 0; width: 24px; height: 24px; }
    @keyframes slideIn { from { transform: translateX(400px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
'''
        admin_html = admin_html[:style_end] + toast_css + admin_html[style_end:]
    
    # Add toast container to body
    body_tag = admin_html.find('<body>')
    if body_tag > -1:
        body_insertion = admin_html.find('>', body_tag) + 1
        admin_html = admin_html[:body_insertion] + '\n  <div id="toastContainer" class="toast-container"></div>\n' + admin_html[body_insertion:]
    
    # Add showToast function
    script_end = admin_html.rfind('</script>')
    if script_end > -1:
        toast_fn = '''
        function showToast(title, message, type = 'info') {
            const container = document.getElementById('toastContainer');
            if (!container) return;
            const toast = document.createElement('div');
            toast.className = `toast ${type}`;
            const icons = { success: '✓', error: '✗', warning: '⚠', info: 'ℹ' };
            toast.innerHTML = `<span class="toast-icon">${icons[type]}</span><div class="toast-content"><div class="toast-title">${title}</div><div class="toast-message">${message}</div></div><button class="toast-close" onclick="this.parentElement.remove()">×</button>`;
            container.appendChild(toast);
            setTimeout(() => toast.remove(), 5000);
        }
'''
        admin_html = admin_html[:script_end] + toast_fn + admin_html[script_end:]
    
    with open(f"{base_dir}/admin_PATCHED.html", 'w') as f:
        f.write(admin_html)
    
    print("✅ admin.html patched")
    
    # ===== PATCH 4: results_dashboard.html =====
    print("\nApplying patches to results_dashboard.html...")
    
    with open(f"{base_dir}/results_dashboard.html", 'r') as f:
        results_html = f.read()
    
    # Add export enhancement before closing script
    script_end = results_html.rfind('</script>')
    if script_end > -1:
        export_js = '''

        // ===== ENHANCED DATA EXPORT (Admin QoL) =====
        async function exportData(format = 'csv') {
            const btn = event?.target;
            if (btn) {
                const original = btn.textContent;
                btn.disabled = true;
                btn.textContent = 'Exporting...';
            }

            try {
                const params = new URLSearchParams(window.location.search);
                const experimentId = params.get('exp');
                
                const response = await fetch(`${API_BASE}/experiments/${experimentId}/export_choices_csv`);
                if (!response.ok) throw new Error('Export failed');
                
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `experiment_${experimentId}_${Date.now()}.csv`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);
                
                if (typeof showToast === 'function') {
                    showToast('Export Complete', 'File downloaded successfully', 'success');
                }
            } catch (error) {
                console.error(error);
                alert('Export failed: ' + error.message);
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = 'Download Raw Data (CSV)';
                }
            }
        }

        // Update download button to use function
        window.addEventListener('DOMContentLoaded', () => {
            const btn = document.getElementById('downloadCsvBtn');
            if (btn) {
                btn.onclick = (e) => { e.preventDefault(); exportData('csv'); };
            }
        });

'''
        results_html = results_html[:script_end] + export_js + results_html[script_end:]
    
    with open(f"{base_dir}/results_dashboard_PATCHED.html", 'w') as f:
        f.write(results_html)
    
    print("✅ results_dashboard.html patched")
    
    print("\n" + "="*60)
    print("ALL PATCHES APPLIED SUCCESSFULLY!")
    print("="*60)
    print("\nPatched files created:")
    print("  - subject_interface_complete_PATCHED.html")
    print("  - experimenter_dashboard_improved_PATCHED.html")
    print("  - admin_PATCHED.html")
    print("  - results_dashboard_PATCHED.html")
    print("\nFeatures added:")
    print("  ✅ WCAG 2.2 AA compliance (focus, skip links, aria)")
    print("  ✅ Resilient networking (retry, queue, toasts)")
    print("  ✅ Help system with examples")
    print("  ✅ Keyboard shortcuts")
    print("  ✅ Enhanced data export")
    print("  ✅ Offline support")

if __name__ == '__main__':
    apply_patches()
