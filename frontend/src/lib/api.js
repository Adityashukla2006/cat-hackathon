export const API_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/$/, '')

export function wsUrl(path) {
  return API_URL.replace(/^http/, 'ws') + path
}

export async function getJson(path, init) {
  const response = await fetch(API_URL + path, init)
  if (!response.ok) {
    throw new Error(`${response.status} ${path}`)
  }
  return response.json()
}

export function postJson(path, body) {
  return getJson(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}
