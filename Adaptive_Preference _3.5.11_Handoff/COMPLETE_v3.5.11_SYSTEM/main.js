const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');

// 1. FIX: Disable Hardware Acceleration to prevent "Network Service" crashes
app.disableHardwareAcceleration();

let pythonProcess = null;

function checkServerReady(callback) {
  // Try to reach the backend health check
  const req = http.get('http://127.0.0.1:5000/api/health', (res) => {
    if (res.statusCode === 200) {
      callback();
    } else {
      setTimeout(() => checkServerReady(callback), 500);
    }
  });

  req.on('error', () => {
    // If server isn't up yet, wait 500ms and try again
    setTimeout(() => checkServerReady(callback), 500);
  });
}

function createWindow() {
  // 2. FIX: Changed '.venv' to 'venv' (Removed the dot) to match your installer script
  // This is why it wasn't finding Python on the new computer
  const pythonPath = path.join(__dirname, 'venv', 'Scripts', 'python.exe');
  const scriptPath = path.join(__dirname, 'backend', 'api.py');
  
  // 3. Launch the backend
  console.log('Attempting to launch Python from:', pythonPath);
  
  pythonProcess = spawn(pythonPath, [scriptPath], {
    env: { ...process.env, FLASK_ENV: 'production' }
  });

  // Log backend output to terminal for debugging
  pythonProcess.stdout.on('data', (data) => console.log(`Python: ${data}`));
  pythonProcess.stderr.on('data', (data) => console.error(`Python Error: ${data}`));

  const win = new BrowserWindow({
    width: 1300,
    height: 900,
    title: "Adaptive Preference Testing System",
    autoHideMenuBar: true,
    show: false, // Don't show the window until it's actually ready
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true
    }
  });

  // 4. WAIT until the server is confirmed healthy, then load and show
  checkServerReady(() => {
    console.log('Backend is ready. Loading Dashboard...');
    win.loadURL('http://127.0.0.1:5000/frontend/admin_PATCHED.html'); 
    win.once('ready-to-show', () => {
      win.show();
    });
  });
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (pythonProcess) pythonProcess.kill();
  app.quit();
});