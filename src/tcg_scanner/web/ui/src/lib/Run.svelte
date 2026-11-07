<script>
  import { onMount } from 'svelte'
  import { getJSON, enc } from './api.js'
  import { loadSort, sortResults } from './sort.js'

  let { name } = $props()
  let run = $state(null)
  let error = $state(null)
  let view = $state(localStorage.getItem('view') || 'grid')
  const initialSort = loadSort()
  let sortField = $state(initialSort.field)
  let sortDir = $state(initialSort.direction)

  onMount(async () => {
    try {
      run = await getJSON(`/api/runs/${enc(name)}`)
    } catch (problem) {
      error = problem.message
    }
  })

  let results = $derived(run ? sortResults(run.results, sortField, sortDir) : [])

  function setView(mode) {
    view = mode
    localStorage.setItem('view', mode)
  }

  function setSort(field) {
    sortField = field
    localStorage.setItem('sortField', field)
  }

  function toggleDirection() {
    sortDir = sortDir === 'asc' ? 'desc' : 'asc'
    localStorage.setItem('sortDir', sortDir)
  }

  function score(value) {
    return value === null || value === undefined ? '—' : value.toFixed(3)
  }

  function money(value, currency) {
    return value === null || value === undefined ? '—' : `${value.toFixed(2)} ${currency}`
  }

  function title(result) {
    return `${result.card_code ?? 'no match'}${result.print_index !== null ? ` #${result.print_index}` : ''}`
  }
</script>

<nav class="crumbs"><a href="#/">Runs</a> <span>›</span> {name}</nav>

{#if error}
  <p class="error">{error}</p>
{:else if !run}
  <p class="muted">Loading…</p>
{:else}
  <section class="page">
    <div class="page-head">
      <h1>{run.name}</h1>
      <span class="muted">{run.groups} cards · {run.photos} photos</span>
    </div>

    <div class="toolbar">
      <div class="view-toggle" role="group" aria-label="view">
        <button class:active={view === 'grid'} onclick={() => setView('grid')}>▦ grid</button>
        <button class:active={view === 'list'} onclick={() => setView('list')}>☰ list</button>
      </div>
      <label class="sort">
        sort
        <select value={sortField} onchange={(event) => setSort(event.currentTarget.value)}>
          <option value="default">file order</option>
          <option value="confidence">confidence</option>
          <option value="price">price</option>
          <option value="usd">USD</option>
          <option value="eur">EUR</option>
          <option value="expansion">expansion</option>
        </select>
      </label>
      <button class="ghost" onclick={toggleDirection} disabled={sortField === 'default'}>
        {sortDir === 'asc' ? '↑ asc' : '↓ desc'}
      </button>
    </div>

    {#if view === 'grid'}
      <div class="album">
        {#each results as result}
          <a class="tile" href={`#/run/${enc(name)}/result/${enc(result.group)}`}>
            <div class="thumb-wrap">
              <img class="thumb" src={result.input_thumb} alt={result.group} loading="lazy" />
              {#if result.reference_thumb}
                <img class="ref" src={result.reference_thumb} alt="reference" loading="lazy" />
              {/if}
              {#if result.warnings.length > 0}
                <span class="warn" title={result.warnings.join(', ')}>!</span>
              {/if}
            </div>
            <div class="tile-meta">
              <strong>{title(result)}</strong>
              <span class="muted">{result.card_name ?? ''}</span>
              <span class="score">{score(result.score)}</span>
            </div>
          </a>
        {/each}
      </div>
    {:else}
      <div class="result-list">
        <div class="list-head">
          <span></span><span>card</span><span>exp</span><span>score</span><span>EUR</span><span>USD</span><span></span>
        </div>
        {#each results as result}
          <a class="row" href={`#/run/${enc(name)}/result/${enc(result.group)}`}>
            <img class="row-thumb" src={result.input_thumb} alt={result.group} loading="lazy" />
            <span class="row-card">
              <strong>{title(result)}</strong>
              <span class="muted">{result.card_name ?? ''}</span>
            </span>
            <span class="muted">{result.expansion ?? '—'}</span>
            <span class="score">{score(result.score)}</span>
            <span>{money(result.price_eur, 'EUR')}</span>
            <span>{money(result.price_usd, 'USD')}</span>
            <span>{#if result.warnings.length > 0}<span class="warn-inline" title={result.warnings.join(', ')}>!</span>{/if}</span>
          </a>
        {/each}
      </div>
    {/if}
  </section>
{/if}
