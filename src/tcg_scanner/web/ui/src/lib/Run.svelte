<script>
  import { onMount } from 'svelte'
  import { getJSON, enc } from './api.js'
  import { loadSort, sortResults } from './sort.js'
  import { startRetry, waitForJob } from './retry.js'

  let { name } = $props()
  let run = $state(null)
  let stats = $state(null)
  let capabilities = $state({ retry: false })
  let error = $state(null)
  let view = $state(localStorage.getItem('view') || 'grid')
  const initialSort = loadSort()
  let sortField = $state(initialSort.field)
  let sortDir = $state(initialSort.direction)
  let selected = $state([])
  let job = $state(null)
  let jobError = $state(null)
  let retrying = $state(false)

  async function load() {
    const [runInfo, statsInfo, caps] = await Promise.all([
      getJSON(`/api/runs/${enc(name)}`),
      getJSON(`/api/runs/${enc(name)}/stats`),
      getJSON('/api/capabilities'),
    ])
    run = runInfo
    stats = statsInfo
    capabilities = caps
  }

  onMount(async () => {
    try {
      await load()
    } catch (problem) {
      error = problem.message
    }
  })

  let results = $derived(run ? sortResults(run.results, sortField, sortDir) : [])

  function eligible(result) {
    return (
      result.is_latest &&
      result.review?.status === 'wrong' &&
      Boolean(result.review?.expansion)
    )
  }

  let eligibleCount = $derived(results.filter(eligible).length)

  function toggle(group) {
    selected = selected.includes(group)
      ? selected.filter((item) => item !== group)
      : [...selected, group]
  }

  function selectAll() {
    const eligibleGroups = results.filter(eligible).map((result) => result.group)
    selected = eligibleGroups.every((group) => selected.includes(group))
      ? []
      : eligibleGroups
  }

  async function retrySelected() {
    if (selected.length === 0) return
    retrying = true
    jobError = null
    try {
      const jobId = await startRetry(name, selected)
      const finished = await waitForJob(jobId, (update) => (job = update))
      job = finished
      selected = []
      await load()
      if (finished.errors?.length) {
        jobError = `${finished.errors.length} item(s) failed`
      }
    } catch (problem) {
      jobError = problem.message
    } finally {
      retrying = false
    }
  }

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

  function retryTitle() {
    if (!capabilities.retry) return 'recognition extra is not installed'
    if (selected.length === 0) return 'select results marked wrong with an expansion'
    return `retry ${selected.length} selected result(s)`
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

    {#if stats}
      <div class="stats">
        <span><strong>{stats.right}</strong> right</span>
        <span><strong>{stats.wrong}</strong> wrong</span>
        <span>{stats.unmarked} unmarked</span>
        <span class="muted">
          accuracy {stats.accuracy === null ? '—' : `${(stats.accuracy * 100).toFixed(1)}%`}
        </span>
      </div>
    {/if}

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

      <span class="toolbar-spacer"></span>

      {#if eligibleCount > 0}
        <button class="ghost" onclick={selectAll} disabled={retrying}>
          {selected.length === eligibleCount ? 'clear selection' : `select all (${eligibleCount})`}
        </button>
      {/if}
      <button
        class="pill bad"
        onclick={retrySelected}
        disabled={retrying || selected.length === 0 || !capabilities.retry}
        title={retryTitle()}
      >
        retry selected{selected.length ? ` (${selected.length})` : ''}
      </button>
    </div>

    {#if job}
      <div class="progress">
        <div class="progress-bar" style={`width:${job.total ? (job.completed / job.total) * 100 : 0}%`}></div>
        <span>{job.completed}/{job.total}{job.current ? ` · ${job.current}` : ''}{job.state === 'failed' ? ' · failed' : ''}</span>
      </div>
    {/if}
    {#if jobError}<p class="error">{jobError}</p>{/if}
    {#if !capabilities.retry}
      <p class="muted small">Retry is disabled: the recognition extra is not installed on the server.</p>
    {/if}

    {#if view === 'grid'}
      <div class="album">
        {#each results as result}
          <div class="tile" class:selected={selected.includes(result.group)}>
            <a class="tile-link" href={`#/run/${enc(name)}/result/${enc(result.group)}`}>
              <div class="thumb-wrap">
                <img class="thumb" src={result.input_thumb} alt={result.group} loading="lazy" />
                {#if result.reference_thumb}
                  <img class="ref" src={result.reference_thumb} alt="reference" loading="lazy" />
                {/if}
                {#if result.warnings.length > 0}
                  <span class="warn" title={result.warnings.join(', ')}>!</span>
                {/if}
                {#if result.review}
                  <span class:ok={result.review.status === 'right'} class:bad={result.review.status === 'wrong'} class="review-badge">
                    {result.review.status === 'right' ? '✓' : result.review.status === 'wrong' ? '✗' : '·'}
                  </span>
                {/if}
                {#if result.version?.hint?.expansion}
                  <span class="retry-badge">retry · {result.version.hint.expansion}</span>
                {/if}
              </div>
              <div class="tile-meta">
                <strong>{title(result)}</strong>
                <span class="muted">{result.card_name ?? ''}</span>
                <span class="score">{score(result.score)}</span>
              </div>
            </a>
            <label
              class="select"
              class:disabled={!eligible(result)}
              title={eligible(result) ? 'select for retry' : 'retry needs a wrong review with an expansion'}
            >
              <input
                type="checkbox"
                checked={selected.includes(result.group)}
                disabled={!eligible(result) || retrying}
                onchange={() => toggle(result.group)}
              />
            </label>
          </div>
        {/each}
      </div>
    {:else}
      <div class="result-list">
        <div class="list-head">
          <span></span>
          <span class="head-cells">
            <span></span><span>card</span><span>exp</span><span>score</span><span>EUR</span><span>USD</span><span></span>
          </span>
        </div>
        {#each results as result}
          <div class="row" class:selected={selected.includes(result.group)}>
            <label class="row-select" title={eligible(result) ? 'select for retry' : 'retry needs a wrong review with an expansion'}>
              <input
                type="checkbox"
                checked={selected.includes(result.group)}
                disabled={!eligible(result) || retrying}
                onchange={() => toggle(result.group)}
              />
            </label>
            <a class="row-link" href={`#/run/${enc(name)}/result/${enc(result.group)}`}>
              <img class="row-thumb" src={result.input_thumb} alt={result.group} loading="lazy" />
              <span class="row-card">
                <strong>{title(result)}</strong>
                <span class="muted">{result.card_name ?? ''}</span>
              </span>
              <span class="muted">{result.expansion ?? '—'}</span>
              <span class="score">{score(result.score)}</span>
              <span>{money(result.price_eur, 'EUR')}</span>
              <span>{money(result.price_usd, 'USD')}</span>
              <span class="marks">
                {#if result.review}
                  <span class:ok={result.review.status === 'right'} class:bad={result.review.status === 'wrong'} class="review-mark">
                    {result.review.status === 'right' ? '✓' : result.review.status === 'wrong' ? '✗' : '·'}
                  </span>
                {/if}
                {#if result.warnings.length > 0}
                  <span class="warn-inline" title={result.warnings.join(', ')}>!</span>
                {/if}
              </span>
            </a>
          </div>
        {/each}
      </div>
    {/if}
  </section>
{/if}
