(function () {
const USER_KEY = 'nutricore_user';
const TOKEN_KEY = 'nutricore_token';
const CART_KEY = 'nutricore_cart';
const CHECKOUT_STATE_KEY = 'nutricore_checkout_state';
const LAST_INVOICE_KEY = 'nutricore_last_invoice';
const authStorage = window.sessionStorage;

function cleanupLegacyAuthStorage() {
  try {
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(TOKEN_KEY);
  } catch (error) {
  }
}

function getToken() {
  try {
    return authStorage.getItem(TOKEN_KEY) || '';
  } catch (error) {
    return '';
  }
}

function getUser() {
  try {
    return JSON.parse(authStorage.getItem(USER_KEY) || 'null');
  } catch (error) {
    return null;
  }
}

function clearClientSession() {
  try {
    authStorage.removeItem(USER_KEY);
    authStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(CART_KEY);
    localStorage.removeItem(CHECKOUT_STATE_KEY);
    localStorage.removeItem(LAST_INVOICE_KEY);
  } catch (error) {
  }
}

function persistSession(user, token) {
  if (token) {
    authStorage.setItem(TOKEN_KEY, token);
  }
  if (user) {
    authStorage.setItem(USER_KEY, JSON.stringify(user));
  }
  cleanupLegacyAuthStorage();
}

function redirectToLogin() {
  clearClientSession();
  window.location.replace('/login.html');
}

async function validateSession(options = {}) {
  const requireAdmin = Boolean(options.requireAdmin);
  const redirectOnFail = Boolean(options.redirectOnFail);
  const adminEmail = String(options.adminEmail || '').trim().toLowerCase();
  const token = getToken();
  const cachedUser = getUser();

  if (!token) {
    clearClientSession();
    if (redirectOnFail) {
      window.location.replace('/login.html');
    }
    return { ok: false, reason: 'missing_token' };
  }

  try {
    const res = await fetch('/user/profile', {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Cache-Control': 'no-store',
        'Pragma': 'no-cache'
      }
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      clearClientSession();
      if (redirectOnFail) {
        window.location.replace('/login.html');
      }
      return { ok: false, reason: 'invalid_token', status: res.status };
    }

    const verifiedUser = { ...(cachedUser || {}), ...(data || {}) };
    persistSession(verifiedUser, token);

    if (requireAdmin) {
      const verifiedEmail = String(verifiedUser.email || '').trim().toLowerCase();
      if (!verifiedUser.is_admin || (adminEmail && verifiedEmail !== adminEmail)) {
        clearClientSession();
        if (redirectOnFail) {
          window.location.replace('/login.html');
        }
        return { ok: false, reason: 'admin_required' };
      }
    }

    return { ok: true, token, user: verifiedUser };
  } catch (error) {
    clearClientSession();
    if (redirectOnFail) {
      window.location.replace('/login.html');
    }
    return { ok: false, reason: 'validation_failed', error };
  }
}

async function redirectIfAuthenticated(options = {}) {
  const session = await validateSession({ redirectOnFail: false });
  if (!session.ok) {
    return false;
  }
  window.location.replace(session.user && session.user.is_admin ? '/adminpanel.html' : '/store');
  return true;
}

window.NutriCoreAuth = {
  USER_KEY,
  TOKEN_KEY,
  getToken,
  getUser,
  clearClientSession,
  persistSession,
  redirectToLogin,
  validateSession,
  redirectIfAuthenticated
};

cleanupLegacyAuthStorage();
}());
