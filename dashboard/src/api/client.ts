const BASE = ''  // same origin, proxied by Vite in dev

export async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${err}`)
  }
  return res.json()
}

export async function patchAPI<T>(path: string, body: Record<string, unknown>): Promise<T> {
  return fetchAPI<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
}

export async function postAPI<T>(path: string, body: Record<string, unknown>): Promise<T> {
  return fetchAPI<T>(path, { method: 'POST', body: JSON.stringify(body) })
}

export async function uploadImageBase64(base64: string, fileName: string): Promise<{ media_id: string }> {
  return postAPI('/api/flow/upload-image-base64', {
    image_base64: base64,
    file_name: fileName,
    mime_type: 'image/png'
  })
}
