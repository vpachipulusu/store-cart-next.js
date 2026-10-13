#!/usr/bin/env node
/* eslint-disable @typescript-eslint/no-require-imports -- CommonJS script (.cjs) */

/**
 * Kill the dev server on the configured port (PORT, default 3000; KAN-167). Only the process listening on that exact
 * port is killed, so a second checkout's server on another port is left alone.
 */

const { exec } = require('child_process');
const fs = require('fs');
const path = require('path');
const { getDevPort } = require('./ports.cjs');

const port = getDevPort();

/**
 * PIDs listening on exactly `port`, from `netstat -ano` output. The local address must end in `:<port>`, so :3000 does
 * not match :30001 or :13000.
 */
function listeningPidsFromNetstat(output, targetPort) {
  const pids = new Set();
  for (const line of output.split(/\r?\n/)) {
    const columns = line.trim().split(/\s+/);
    // Proto, Local Address, Foreign Address, State, PID
    if (
      columns.length >= 5 &&
      columns[3] === 'LISTENING' &&
      columns[1].endsWith(`:${targetPort}`)
    ) {
      pids.add(columns[4]);
    }
  }
  return pids;
}

function printDone() {
  console.log('\n✨ All clean! Run "npm run dev" to start\n');
}

function killWindows() {
  // Use exec instead of execSync to avoid killing ourselves
  exec('netstat -ano -p tcp', (error, stdout) => {
    const pids = listeningPidsFromNetstat(stdout || '', port);
    pids.delete(String(process.pid));

    if (pids.size === 0) {
      console.log(`ℹ No processes found on port ${port}`);
      printDone();
      return;
    }

    console.log(`Found ${pids.size} process(es) on port ${port}`);
    pids.forEach((pid) => {
      exec(`taskkill /F /PID ${pid}`, (err) => {
        if (!err) {
          console.log(`✓ Killed process ${pid}`);
        }
      });
    });

    // Wait a bit for kills to complete
    setTimeout(printDone, 500);
  });
}

function killUnix() {
  exec(`lsof -ti tcp:${port} -sTCP:LISTEN`, (error, stdout) => {
    const pids = (stdout || '')
      .trim()
      .split('\n')
      .filter((pid) => pid && pid !== String(process.pid));

    if (pids.length === 0) {
      console.log(`ℹ No processes found on port ${port}`);
      printDone();
      return;
    }

    exec(`kill -9 ${pids.join(' ')}`, (err) => {
      if (!err) {
        console.log(`✓ Killed ${pids.length} process(es)`);
      }
      printDone();
    });
  });
}

if (require.main === module) {
  console.log('🔪 Terminating development processes...\n');

  // Clean up lock file first
  const lockFile = path.join(process.cwd(), '.next', 'dev', 'lock');
  if (fs.existsSync(lockFile)) {
    try {
      fs.unlinkSync(lockFile);
      console.log('✓ Removed lock file');
    } catch {
      console.warn('⚠ Could not remove lock file');
    }
  }

  console.log(`Looking for processes on port ${port}...`);
  if (process.platform === 'win32') {
    killWindows();
  } else {
    killUnix();
  }
}

module.exports = { listeningPidsFromNetstat };
