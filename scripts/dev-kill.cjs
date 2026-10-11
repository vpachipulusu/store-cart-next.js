#!/usr/bin/env node

const { exec } = require('child_process');
const fs = require('fs');
const path = require('path');

console.log('🔪 Terminating development processes...\n');

// Clean up lock file first
const lockFile = path.join(process.cwd(), '.next', 'dev', 'lock');
if (fs.existsSync(lockFile)) {
  try {
    fs.unlinkSync(lockFile);
    console.log('✓ Removed lock file');
  } catch (err) {
    console.warn('⚠ Could not remove lock file');
  }
}

if (process.platform === 'win32') {
  console.log('Looking for processes on port 3000...');

  // Use exec instead of execSync to avoid killing ourselves
  exec('netstat -ano | findstr :3000', (error, stdout) => {
    if (stdout) {
      const lines = stdout.split('\n');
      const pids = new Set();

      for (const line of lines) {
        const match = line.match(/LISTENING\s+(\d+)/);
        if (match && match[1] && match[1] !== String(process.pid)) {
          pids.add(match[1]);
        }
      }

      if (pids.size > 0) {
        console.log(`Found ${pids.size} process(es) on port 3000`);
        pids.forEach(pid => {
          exec(`taskkill /F /PID ${pid}`, (err) => {
            if (!err) {
              console.log(`✓ Killed process ${pid}`);
            }
          });
        });

        // Wait a bit for kills to complete
        setTimeout(() => {
          console.log('\n✨ All clean! Run "npm run dev" to start\n');
        }, 500);
      } else {
        console.log('ℹ No processes found on port 3000');
        console.log('\n✨ All clean! Run "npm run dev" to start\n');
      }
    } else {
      console.log('ℹ No processes found on port 3000');
      console.log('\n✨ All clean! Run "npm run dev" to start\n');
    }
  });
} else {
  // Unix/Mac/Linux
  console.log('Looking for processes on port 3000...');

  exec('lsof -ti:3000', (error, stdout) => {
    if (stdout && stdout.trim()) {
      const pids = stdout.trim().split('\n').filter(pid => pid !== String(process.pid));

      if (pids.length > 0) {
        exec(`kill -9 ${pids.join(' ')}`, (err) => {
          if (!err) {
            console.log(`✓ Killed ${pids.length} process(es)`);
          }
          console.log('\n✨ All clean! Run "npm run dev" to start\n');
        });
      } else {
        console.log('ℹ No processes found on port 3000');
        console.log('\n✨ All clean! Run "npm run dev" to start\n');
      }
    } else {
      console.log('ℹ No processes found on port 3000');
      console.log('\n✨ All clean! Run "npm run dev" to start\n');
    }
  });
}
