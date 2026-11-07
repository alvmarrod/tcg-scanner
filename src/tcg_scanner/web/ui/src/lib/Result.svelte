<script>
  import { onMount } from 'svelte'
  import { getJSON, enc } from './api.js'
  import { loadSort, sortResults } from './sort.js'
  import { startRetry, waitForJob } from './retry.js'

  let { run, group } = $props()
  let detail = $state(null)
  let runData = $state(null)
  let expansions = $state([])
  let capabilities = $state({ retry: false })
  let error = $state(null)

  let iteration = $state(null)
  let review = $state(null)
  let expansion = $state('')
  let note = $state('')
  let saving = $state(false)
  let reviewError = $state(null)

  let retrying = $state(false)
  let job = $state(null)
  let jobError = $state(null)

  const sort = loadSort()

  onMount(async () => {
    try {
      const [runInfo, expansionInfo, caps] = await Promise.all([
        getJSON(`/api/runs/${enc(run)}`),
        getJSON('/api/expansions'),
        getJSON('/api/capabilities'),
      ])
      runData = runInfo
      expansions = expansionInfo.expansions
      capabilities = caps
      await loadDetail(null)
    } catch (problem) {
      error = problem.message
    }
  })

  async function loadRun() {
    runData = await getJSON(`/api/runs/${enc(run)}`)
  }

  async function loadDetail(number) {
    const query =
      number === null || number === undefined ? '' : `?iteration=${number}`
    const result = await getJSON(
      `/api/runs/${enc(run)}/results/${enc(group)}${query}`,
    )
    detail = result
    iteration = result.iteration
    review = result.summary.review
    expansion = review?.expansion ?? ''
    note = review?.note ?? ''
  }

  let ordered = $derived(
    runData ? sortResults(runData.results, sort.field, sort.direction) : [],
  )
  let index = $derived(ordered.findIndex((item) => item.group === group))
  let previous = $derived(index > 0 ? ordered[index - 1] : null)
  let next = $derived(index >= 0 && index < ordered.length - 1 ? ordered[index + 1] : null)

  function go(target) {
    if (target) location.hash = `#/run/${enc(run)}/result/${enc(target.group)}`
  }

  onMount(() => {
    const key = (event) => {
      if (event.key === 'ArrowLeft') go(previous)
      if (event.key === 'ArrowRight') go(next)
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  })

  let summary = $derived(detail?.summary)
  let report = $derived(detail?.report)
  let isLatest = $derived(Boolean(summary?.is_latest))
  let estate = $derived(
    review?.status === 'right'
      ? 'Confirmed'
      : review?.status === 'wrong'
        ? 'Wrong'
        : 'Unmarked',
  )
  let estateClass = $derived(
    review?.status === 'right' ? 'ok' : review?.status === 'wrong' ? 'bad' : 'neutral',
  )
  let canRetry = $derived(
    isLatest && review?.status === 'wrong' && Boolean(review?.expansion),
  )
  let hint = $derived(summary?.version?.hint ?? null)

  async function putReview(payload) {
    saving = true
    reviewError = null
    try {
      const response = await fetch(
        `/api/runs/${enc(run)}/results/${enc(group)}/review`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      )
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.detail || `${response.status} ${response.statusText}`)
      }
      return await response.json()
    } finally {
      saving = false
    }
  }

  async function applyReview(payload) {
    try {
      review = await putReview(payload)
      if (review === null) {
        expansion = ''
        note = ''
      } else {
        expansion = review.expansion ?? expansion
      }
    } catch (problem) {
      reviewError = problem.message
    }
  }

  function saveStatus(status) {
    applyReview({
      status,
      expansion: status === 'wrong' ? expansion || null : null,
      note: note || null,
    })
  }

  function saveDetails() {
    const status = expansion
      ? 'wrong'
      : review?.status === 'right' || review?.status === 'wrong'
        ? review.status
        : 'unmarked'
    applyReview({ status, expansion: expansion || null, note: note || null })
  }

  function clearWrong() {
    applyReview({
      status: 'unmarked',
      expansion: expansion || null,
      note: note || null,
    })
  }

  function clearExpansion() {
    applyReview({
      status: review?.status ?? 'unmarked',
      expansion: null,
      note: note || null,
    })
  }

  async function retry() {
    retrying = true
    jobError = null
    try {
      const jobId = await startRetry(run, [group])
      const finished = await waitForJob(jobId, (update) => (job = update))
      job = finished
      await Promise.all([loadDetail(null), loadRun()])
    } catch (problem) {
      jobError = problem.message
    } finally {
      retrying = false
    }
  }
</script>

<nav class="crumbs">
  <a href="#/">Runs</a> <span>›</span>
  <a href={`#/run/${enc(run)}`}>{run}</a> <span>›</span>
  {group}
</nav>

{#if error}
  <p class="error">{error}</p>
{:else if !detail}
  <p class="muted">Loading…</p>
{:else}
  <section class="page">
    <div class="page-head">
      <h1>{summary.card_code ?? 'No match'}{summary.print_index !== null ? ` #${summary.print_index}` : ''}</h1>
      <span class="muted">{summary.card_name ?? ''}</span>
      <span class="score-big">{summary.score !== null ? summary.score.toFixed(3) : '—'}</span>
    </div>

    <div class="version-bar">
      <span class="muted">version</span>
      <select value={iteration} onchange={(event) => loadDetail(Number(event.currentTarget.value))}>
        {#each detail.history as version}
          <option value={version.iteration}>
            v{version.iteration} · {version.version?.kind ?? 'batch'}{version.version?.hint?.expansion ? ` · ${version.version.hint.expansion}` : ''}
          </option>
        {/each}
      </select>
      {#if !isLatest}<span class="version-note">older version · read only</span>{/if}
      {#if hint}
        <span class="version-note">
          hint: {hint.status}{hint.expansion ? ` → ${hint.expansion}` : ''}{hint.note ? ` · ${hint.note}` : ''}
        </span>
      {/if}
    </div>

    <div class="detail-top">
      <figure class="detail-photo">
        <img src={summary.input_url} alt="input photo" />
        <figcaption class="muted">input · {report.photos.length} photo{report.photos.length === 1 ? '' : 's'}</figcaption>
      </figure>
      <figure class="detail-photo">
        {#if summary.reference_url}
          <img src={summary.reference_url} alt="catalog reference" />
          <figcaption class="muted">reference · {summary.reference_language ?? 'unknown'}</figcaption>
        {:else}
          <div class="placeholder">no reference image</div>
          <figcaption class="muted">reference</figcaption>
        {/if}
      </figure>
      <aside class="detail-side">
        <div class="panel">
          <h2>Match</h2>
          <dl>
            <dt>estate</dt><dd class="estate {estateClass}">{estate}{review?.expansion ? ` · ${review.expansion}` : ''}</dd>
            <dt>score</dt><dd>{summary.score !== null ? summary.score.toFixed(3) : '—'}</dd>
            <dt>patch</dt><dd>{summary.patch_score !== null ? summary.patch_score.toFixed(3) : '—'}</dd>
            <dt>margin</dt><dd>{summary.margin !== null ? summary.margin.toFixed(3) : '—'}</dd>
            <dt>set</dt><dd>{summary.set_code ?? '—'}</dd>
            <dt>variant</dt><dd>{summary.variant_label ?? '—'}</dd>
            <dt>OCR</dt><dd>{summary.ocr_code ?? 'unreadable'}</dd>
            <dt>reference</dt><dd>{summary.reference_language ?? '—'}</dd>
            <dt>EUR</dt><dd>{report.prices?.eur ?? '—'}</dd>
            <dt>USD</dt><dd>{report.prices?.usd ?? '—'}</dd>
          </dl>
        </div>
        <div class="panel">
          <h2>Candidates</h2>
          <ol class="candidates">
            {#each report.candidates as candidate}
              <li>
                <span>{candidate.card_code} #{candidate.print_index}</span>
                <span class="muted">{candidate.score.toFixed(3)}</span>
              </li>
            {/each}
          </ol>
        </div>
      </aside>
    </div>

    <div class="nav-row">
      <button class="ghost" disabled={!previous} onclick={() => go(previous)}>← previous</button>
      <span class="muted">{index + 1} / {ordered.length}</span>
      <button class="ghost" disabled={!next} onclick={() => go(next)}>next →</button>
    </div>

    {#if report.warnings.length > 0}
      <ul class="warnings">
        {#each report.warnings as warning}
          <li><code>{warning.code}</code> {warning.message}</li>
        {/each}
      </ul>
    {/if}

    <div class="panel review-panel">
      <div class="review-head">
        <h2>Review</h2>
        {#if review?.stale}
          <span class="warn-text">this review refers to an older prediction</span>
        {/if}
      </div>
      <div class="review-actions">
        <button
          class="pill ok"
          class:active={review?.status === 'right'}
          disabled={!isLatest || saving}
          onclick={() => saveStatus('right')}
        >✓ right</button>
        <button
          class="pill bad"
          class:active={review?.status === 'wrong'}
          disabled={!isLatest || saving}
          onclick={() => saveStatus('wrong')}
        >✗ wrong</button>
        {#if review}
          <button class="ghost" disabled={!isLatest || saving} onclick={clearWrong}>clear wrong</button>
          <button class="ghost" disabled={!isLatest || saving} onclick={clearExpansion}>clear expansion</button>
        {/if}
      </div>

      <div class="review-fields">
        <label>correct expansion
          <input
            list="expansions"
            bind:value={expansion}
            placeholder="OP15"
            disabled={!isLatest || saving}
            onchange={() => { if (expansion) saveDetails() }}
          />
        </label>
        <label>note
          <input bind:value={note} placeholder="optional" disabled={!isLatest || saving} />
        </label>
        <button class="ghost" disabled={!isLatest || saving} onclick={saveDetails}>save details</button>
      </div>
      <datalist id="expansions">
        {#each expansions as value}<option value={value}></option>{/each}
      </datalist>
      {#if !isLatest}<p class="version-note">Select the latest version to edit its review.</p>{/if}
      {#if reviewError}<p class="error">{reviewError}</p>{/if}
    </div>

    <div class="panel retry-row">
      <button
        class="ghost"
        disabled={!canRetry || retrying || !capabilities.retry}
        onclick={retry}
        title={!capabilities.retry ? 'recognition extra is not installed' : !canRetry ? 'needs a wrong review with an expansion' : ''}
      >
        retry within {review?.expansion ?? 'expansion'}
      </button>
      {#if !capabilities.retry}
        <span class="version-note">retry is disabled: the recognition extra is not installed on the server</span>
      {/if}
      {#if job}
        <div class="progress" style="flex:1">
          <div class="progress-bar" style={`width:${job.total ? (job.completed / job.total) * 100 : 0}%`}></div>
          <span>{job.completed}/{job.total}{job.state === 'failed' ? ' · failed' : ''}</span>
        </div>
      {/if}
      {#if jobError}<p class="error">{jobError}</p>{/if}
    </div>

    <details class="raw">
      <summary class="muted">raw result JSON</summary>
      <pre>{JSON.stringify(report, null, 2)}</pre>
    </details>
  </section>
{/if}
