export async function getJSON(url) {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
  return response.json()
}

export const enc = encodeURIComponent
