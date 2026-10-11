import * as OTPAuth from 'otpauth';

const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME || 'SaaS Boilerplate';

/**
 * Generate a new TOTP secret for a user
 */
export function generateTOTPSecret(userEmail: string) {
  const secret = new OTPAuth.Secret({ size: 20 });

  const totp = new OTPAuth.TOTP({
    issuer: APP_NAME,
    label: userEmail,
    algorithm: 'SHA1',
    digits: 6,
    period: 30,
    secret,
  });

  return {
    secret: secret.base32,
    uri: totp.toString(), // otpauth:// URI for QR code generation
  };
}

/**
 * Verify a TOTP token against a secret
 */
export function verifyTOTPToken(token: string, secret: string): boolean {
  const totp = new OTPAuth.TOTP({
    issuer: APP_NAME,
    algorithm: 'SHA1',
    digits: 6,
    period: 30,
    secret: OTPAuth.Secret.fromBase32(secret),
  });

  const delta = totp.validate({ token, window: 1 }); // Allow 1 period of drift
  return delta !== null;
}
