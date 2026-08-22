const BASE = ''  // same origin, proxied by Vite in dev

function csrfToken(): string {
  if (typeof document === 'undefined') return ''
  const prefix = 'bosmax_csrf='
  const item = document.cookie.split('; ').find((value) => value.startsWith(prefix))
  return item ? decodeURIComponent(item.slice(prefix.length)) : ''
}

function requestHeaders(options?: RequestInit): HeadersInit {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options?.headers as Record<string, string> | undefined),
  }
  const method = (options?.method ?? 'GET').toUpperCase()
  const token = csrfToken()
  if (token && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    headers['X-CSRF-Token'] = token
  }
  return headers
}

export async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    credentials: 'same-origin',
    headers: requestHeaders(options),
  })
  if (!res.ok) {
    const err = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${err}`)
  }
  return res.json()
}

export async function getAPI<T>(path: string): Promise<T> {
  return fetchAPI<T>(path, { method: 'GET' })
}

export async function patchAPI<T>(path: string, body: any): Promise<T> {
  return fetchAPI<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
}

export async function postAPI<T>(path: string, body: any): Promise<T> {
  return fetchAPI<T>(path, { method: 'POST', body: JSON.stringify(body) })
}

export async function deleteAPI(path: string): Promise<void> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'DELETE',
    credentials: 'same-origin',
    headers: requestHeaders({ method: 'DELETE' }),
  })
  if (!res.ok) {
    const err = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${err}`)
  }
}

export async function postMultipartAPI<T>(path: string, body: FormData): Promise<T> {
  const token = csrfToken()
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: token ? { 'X-CSRF-Token': token } : undefined,
    body,
  })
  if (!res.ok) {
    const err = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${err}`)
  }
  return res.json()
}

export async function uploadImageBase64(
	base64: string,
	fileName: string,
): Promise<{
	media_id: string;
	file_name: string;
	mime_type: string;
	local_file_path: string;
}> {
  return postAPI('/api/flow/upload-image-base64', {
    image_base64: base64,
    file_name: fileName,
    mime_type: 'image/png'
  })
}
