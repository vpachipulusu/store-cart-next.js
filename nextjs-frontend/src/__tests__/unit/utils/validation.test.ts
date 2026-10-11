import { describe, it, expect } from 'vitest';

// Validation utility functions to be implemented
export function validateEmail(email: string): boolean {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
}

export function validatePassword(password: string): { valid: boolean; message?: string } {
  if (!password || password.length < 8) {
    return {
      valid: false,
      message: 'Password must be at least 8 characters long',
    };
  }
  return { valid: true };
}

describe('Validation Utils', () => {
  describe('Email Validation', () => {
    describe('Given a valid email address', () => {
      it('should return true for standard email format', () => {
        expect(validateEmail('user@example.com')).toBe(true);
      });

      it('should return true for email with subdomains', () => {
        expect(validateEmail('user@mail.example.com')).toBe(true);
      });

      it('should return true for email with plus addressing', () => {
        expect(validateEmail('user+tag@example.com')).toBe(true);
      });
    });

    describe('Given an invalid email address', () => {
      it('should return false for missing @ symbol', () => {
        expect(validateEmail('userexample.com')).toBe(false);
      });

      it('should return false for missing domain', () => {
        expect(validateEmail('user@')).toBe(false);
      });

      it('should return false for spaces in email', () => {
        expect(validateEmail('user @example.com')).toBe(false);
      });

      it('should return false for empty string', () => {
        expect(validateEmail('')).toBe(false);
      });
    });
  });

  describe('Password Validation', () => {
    describe('Given a valid password', () => {
      it('should accept password with 8 characters', () => {
        const result = validatePassword('pass1234');
        expect(result.valid).toBe(true);
        expect(result.message).toBeUndefined();
      });

      it('should accept password with 20 characters', () => {
        const result = validatePassword('a'.repeat(20));
        expect(result.valid).toBe(true);
      });
    });

    describe('Given an invalid password', () => {
      it('should reject password with less than 8 characters', () => {
        const result = validatePassword('pass12');
        expect(result.valid).toBe(false);
        expect(result.message).toBe('Password must be at least 8 characters long');
      });

      it('should reject empty password', () => {
        const result = validatePassword('');
        expect(result.valid).toBe(false);
      });
    });
  });
});
