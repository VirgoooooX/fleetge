export function redirectToLogin() {
  localStorage.removeItem("token");
  localStorage.removeItem("username");
  if (window.location.pathname !== "/login") {
    const redirect = `${window.location.pathname}${window.location.search}`;
    window.location.replace(`/login?redirect=${encodeURIComponent(redirect)}`);
  }
}
