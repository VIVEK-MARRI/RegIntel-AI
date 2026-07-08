let _token: string | null = null;

export function setAccessToken(token: string | null) {
  _token = token;
}

export function getAccessToken(): string | null {
  return _token;
}
