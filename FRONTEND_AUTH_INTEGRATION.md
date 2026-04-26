# Frontend Authentication Integration Guide

ShiftReady uses **Firebase Authentication** for identity management. The backend is already configured to validate Firebase ID Tokens and synchronize user profiles in Firestore.

## 🔐 Supported Providers
Since we use the Firebase Admin SDK on the backend, you can implement any of the following on the frontend:
- **Social**: Google, Apple, GitHub, etc.
- **Passwordless**: Email Link.
- **Traditional**: Email/Password.

---

## 1. Firebase Client SDK Setup
You will need to install the Firebase JS SDK in the UI project:
```bash
npm install firebase
```

Initialize Firebase using the config found in the [GCP/Firebase Console](https://console.firebase.google.com/):
```javascript
import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";

const firebaseConfig = {
  apiKey: "...",
  authDomain: "shiftready-backend.firebaseapp.com",
  projectId: "shiftready-backend",
  // ... rest of config
};

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
```

## 2. Getting the ID Token
The backend **cannot** use the Access Token. You must explicitly retrieve the **ID Token** (JWT) after the user signs in.

```javascript
import { GoogleAuthProvider, signInWithPopup } from "firebase/auth";

const provider = new GoogleAuthProvider();

async function handleLogin() {
  const result = await signInWithPopup(auth, provider);
  // This is the token the backend needs
  const idToken = await result.user.getIdToken();
  
  // Store this in your state management or SecureCookie
  console.log("JWT:", idToken);
}
```

## 3. Communicating with the Backend

### A. REST API Calls
Include the token in the `Authorization` header as a `Bearer` token for all requests.

```javascript
const response = await fetch('https://<backend-url>/api/v1/sales/init', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${idToken}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({ filename: 'walkthrough.mp4' })
});
```

### B. WebSockets (Status Updates)
Since WebSockets do not easily support custom headers in the browser, pass the token as a **query parameter**.

```javascript
const eventId = "some-uuid";
const ws = new WebSocket(`ws://<backend-url>/api/v1/sales/${eventId}/ws?token=${idToken}`);

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log("Status Update:", data.status);
};
```

## 4. Local Development (Mock Auth)
The backend has a bypass for local development. If you are running the backend locally (and `K_SERVICE` environment variable is not set), you can use a mock token.

- **Mock Token Format**: `dev_<your_name>` (e.g., `dev_ajay_2026`)
- **Behavior**: The backend will skip Firebase validation and create a dummy user record for you.

## 5. Permissions
If you need access to the GCP Project to configure the Auth Providers (Enable Apple/Google), ask the Project Owner for the **Firebase Authentication Admin** role.

---
*ShiftReady Engineering 2026*
