# Authentication Implementation

## Steps

1. Choose authentication method:
   - JWT (stateless, good for APIs)
   - Session-based (good for traditional web apps)
   - OAuth2/OIDC (external providers, SSO)
   - API keys (service-to-service)

2. For JWT authentication:
   - Install dependencies: `python-jose[cryptography], passlib[bcrypt]`
   - Create `auth/jwt.py` with token generation/validation
   - Define secret key and algorithm (HS256 or RS256)
   - Set token expiration (access: 15min, refresh: 7d)

3. Implement password hashing:
   - Use bcrypt or argon2
   - Hash on user creation/update
   - Verify on login

4. Create authentication endpoints:
   - POST /auth/register - User registration
   - POST /auth/login - Issue tokens
   - POST /auth/refresh - Refresh access token
   - POST /auth/logout - Invalidate token (if using blocklist)

5. Add authentication dependency:
   - Create `get_current_user` dependency
   - Extract and validate JWT from Authorization header
   - Fetch user from database
   - Handle expired/invalid tokens

6. Add authorization decorators:
   - Create `require_role` dependency
   - Check user roles/permissions
   - Return 403 for unauthorized access

7. Secure endpoints:
   - Add `Depends(get_current_user)` to protected routes
   - Add `Depends(require_role("admin"))` for role-restricted routes
   - Document authentication in OpenAPI spec

8. Implement token refresh:
   - Store refresh tokens in database with expiration
   - Invalidate on logout or token rotation
   - Consider token rotation for security

9. Add rate limiting to auth endpoints:
   - Prevent brute force on login
   - Limit registration attempts
   - Use Redis for distributed rate limiting

10. Test authentication flows:
    - Test successful login/token issuance
    - Test expired tokens
    - Test invalid tokens
    - Test unauthorized access
    - Test role-based access control
