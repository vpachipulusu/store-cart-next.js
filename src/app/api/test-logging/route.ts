import { NextRequest, NextResponse } from 'next/server';
import { logger } from '@/lib/logger';

/**
 * Test endpoint for logging
 * GET /api/test-logging
 */
export async function GET(request: NextRequest) {
  try {
    console.log('[TEST] Endpoint called - about to call logger');

    // Test all log levels
    logger.info('TEST: Test API endpoint called', {
      url: request.url,
      method: request.method,
      timestamp: new Date().toISOString(),
    });

    console.log('[TEST] After logger.info call');

    logger.debug('TEST: Debug test from API', {
      debugData: 'This is a debug message',
    });

    logger.warn('TEST: Warning test from API', {
      warningData: 'This is a warning message',
    });

    logger.error('TEST: Error test from API', {
      errorData: 'This is a test error message',
      error: new Error('Test error'),
    });

    console.log('[TEST] All logger calls completed');

    return NextResponse.json({
      success: true,
      message: 'Logging test completed',
      info: 'Check /logs folder for log files and terminal for console output',
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    console.error('[TEST] Error in test endpoint:', error);
    logger.error('Test logging endpoint error', { error });
    return NextResponse.json({ success: false, error: 'Logging test failed' }, { status: 500 });
  }
}
