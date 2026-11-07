export function loadSort() {
  return {
    field: localStorage.getItem('sortField') || 'default',
    direction: localStorage.getItem('sortDir') || 'desc',
  }
}

function value(result, field) {
  if (field === 'confidence') return result.score
  if (field === 'price') return result.price
  if (field === 'usd') return result.price_usd
  if (field === 'eur') return result.price_eur
  if (field === 'expansion') return result.expansion
  return null
}

export function sortResults(results, field, direction) {
  if (field === 'default') return [...results]
  const sign = direction === 'asc' ? 1 : -1
  return [...results].sort((a, b) => {
    const left = value(a, field)
    const right = value(b, field)
    if (left == null && right == null) return 0
    if (left == null) return 1
    if (right == null) return -1
    if (left < right) return -1 * sign
    if (left > right) return 1 * sign
    return 0
  })
}
