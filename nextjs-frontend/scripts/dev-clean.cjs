#!/usr/bin/env node
/* eslint-disable @typescript-eslint/no-require-imports -- CommonJS script (.cjs) */

/**
 * Clean development script
 * Removes stale Next.js lock files before starting dev server
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { getDevPort } = require('./ports.cjs');

const port = getDevPort();

const lockFile = path.join(process.cwd(), '.next', 'dev', 'lock');
const nextDir = path.join(process.cwd(), '.next');

console.log('🧹 Cleaning up...');

// Remove lock file if it exists
if (fs.existsSync(lockFile)) {
  try {
    fs.unlinkSync(lockFile);
    console.log('✓ Removed stale lock file');
  } catch (error) {
    console.warn('⚠ Could not remove lock file:', error.message);
  }
}

// Check for running Next.js processes and offer to kill them
try {
  if (process.platform === 'win32') {
    // Windows: Check for Node processes running Next.js
    const processes = execSync('tasklist /FI "IMAGENAME eq node.exe" /FO CSV /NH', {
      encoding: 'utf8',
      stdio: ['pipe', 'pipe', 'ignore'],
    });

    if (processes.includes('node.exe')) {
      console.log('⚠ Found running Node.js processes');
      console.log('  Run "npm run dev:kill" to terminate them if needed');
    }
  } else {
    // Unix-like: Check for processes on the dev port (PORT, default 3000)
    try {
      execSync(`lsof -ti tcp:${port} -sTCP:LISTEN`, {
        encoding: 'utf8',
        stdio: ['pipe', 'pipe', 'ignore'],
      });
      console.log(`⚠ Port ${port} is in use`);
      console.log('  Run "npm run dev:kill" to free it');
    } catch {
      // Port is free
    }
  }
} catch (error) {
  // Ignore errors in process checking
}

console.log('✨ Ready to start dev server\n');
