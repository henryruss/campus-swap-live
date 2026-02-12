# Google Sign-In Setup

To enable "Sign in with Google" on the create account and login pages:

## 1. Create OAuth credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. APIs & Services → Credentials → Create Credentials → OAuth client ID
4. Application type: **Web application**
5. Add Authorized redirect URIs:
   - Local: `http://localhost:5000/auth/google/callback`
   - Production: `https://your-domain.com/auth/google/callback`

## 2. Set environment variables

Add to your `.env` (local) or Render Environment (production):

```
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret
```

If these are not set, the Google sign-in button is hidden and users use the email form only.
