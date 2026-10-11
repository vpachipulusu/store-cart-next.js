#!/usr/bin/env node

/**
 * Script to test logging functionality
 * Run with: node scripts/test-logging.mjs
 */

// Test the logger by importing it
const { logger } = await import('../src/lib/logger.ts');

console.log('Testing logger functionality...\n');

// Test all log levels
logger.info('Test info message', { testData: 'info test', timestamp: new Date().toISOString() });
logger.warn('Test warning message', {
  testData: 'warning test',
  timestamp: new Date().toISOString(),
});
logger.error('Test error message', {
  testData: 'error test',
  error: 'This is a test error',
  timestamp: new Date().toISOString(),
});
logger.debug('Test debug message', { testData: 'debug test', timestamp: new Date().toISOString() });

console.log('\n✓ Log messages sent');
console.log('→ Check the /logs folder for:');
console.log('  - app-YYYY-MM-DD.log (should contain all messages)');
console.log('  - error-YYYY-MM-DD.log (should contain only error message)');

// Give it a moment to flush
setTimeout(() => {
  console.log('\n✓ Logs should now be written to disk');
  process.exit(0);
}, 1000);
