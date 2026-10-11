// Simple test to verify Winston logging works
// Run with: node --loader ts-node/esm scripts/test-winston.mjs

import { logger } from '../src/lib/logger.ts';

console.log('=== Testing Winston Logger ===\n');

// Generate test logs
logger.info('Test log entry 1 - Info level');
logger.debug('Test log entry 2 - Debug level');
logger.warn('Test log entry 3 - Warn level');
logger.error('Test log entry 4 - Error level', {
  error: 'Test error object',
  stack: 'Test stack trace',
});

console.log('\n✓ Test logs sent');
console.log('Waiting 2 seconds for writes to flush...\n');

setTimeout(() => {
  logger.info('Test log entry 5 - Final info');
  console.log('✓ All logs sent');
  console.log('\nCheck /logs/app-YYYY-MM-DD.log and /logs/error-YYYY-MM-DD.log');

  // Give a moment for final flush
  setTimeout(() => {
    console.log('✓ Test complete\n');
    process.exit(0);
  }, 2000);
}, 2000);
