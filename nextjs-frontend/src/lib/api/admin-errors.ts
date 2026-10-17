import 'server-only';

import type { ApiResult } from './server';

/**
 * Curated messages for failed admin API results, shared by every admin page and action. Backend error text is
 * never passed through: only the status decides the wording, so raw detail (ids, SQL, upstream errors) cannot
 * reach the admin's browser.
 */

export const ADMIN_FORBIDDEN_MESSAGE = 'You do not have permission to do that';
export const ADMIN_NOT_FOUND_MESSAGE = 'Not found';
export const ADMIN_REQUEST_FAILED_MESSAGE = 'Something went wrong. Please try again.';
export const ADMIN_UNAVAILABLE_MESSAGE =
  'The admin service is unavailable. Please try again later.';

export const ADMIN_SYNC_RATE_LIMITED_MESSAGE =
  'Too many checks in a row. Wait a minute and try again.';

type FailedResult = Extract<ApiResult<unknown>, { success: false }>;

/** `notFoundMessage` lets a page about one kind of thing say what was not found. */
export function adminErrorMessage(
  result: FailedResult,
  notFoundMessage: string = ADMIN_NOT_FOUND_MESSAGE
): string {
  switch (result.status) {
    case 401:
    case 403:
      return ADMIN_FORBIDDEN_MESSAGE;
    case 404:
      return notFoundMessage;
    case undefined:
      return ADMIN_UNAVAILABLE_MESSAGE;
    default:
      return ADMIN_REQUEST_FAILED_MESSAGE;
  }
}
