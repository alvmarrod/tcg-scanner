<script>
  import { onMount } from 'svelte'
  import { getJSON, enc } from './api.js'
  import { loadSort, sortResults } from './sort.js'

  let { run, group } = $props()
  let detail = $state(null)
  let runData = $state(null)
  let error = $state(null)

  onMount(async () => {
    try {
      const [result, runInfo] = await Promise.all([
        getJSON(`/api/runs/${enc(run)}/results/${enc(group)}`),
        getJSON(`/api/runs/${enc(run)}`),
      ])
      detail = result
      runData = runInfo
    } catch (problem) {
      error = problem.message
    }
  })

  const sort = loadSort()
  let ordered = $derived(runData ? sortResults(runData.results, sort.field, sort.direction) : [])
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
  let detection = $derived(report?.detections?.[0])
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

    <div class="compare">
      <figure>
        <img src={summary.input_url} alt="input photo" />
        <figcaption class="muted">input · {report.photos.length} photo{report.photos.length === 1 ? '' : 's'}</figcaption>
      </figure>
      <figure>
        {#if summary.reference_url}
          <img src={summary.reference_url} alt="catalog reference" />
          <figcaption class="muted">reference · {summary.reference_language ?? 'unknown'}</figcaption>
        {:else}
          <div class="placeholder">no reference image</div>
          <figcaption class="muted">reference</figcaption>
        {/if}
      </figure>
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

    <div class="panels">
      <div class="panel">
        <h2>Match</h2>
        <dl>
          <dt>score</dt><dd>{summary.score !== null ? summary.score.toFixed(3) : '—'}</dd>
          <dt>patch</dt><dd>{summary.patch_score !== null ? summary.patch_score.toFixed(3) : '—'}</dd>
          <dt>margin</dt><dd>{summary.margin !== null ? summary.margin.toFixed(3) : '—'}</dd>
          <dt>set</dt><dd>{summary.set_code ?? '—'}</dd>
          <dt>variant</dt><dd>{summary.variant_label ?? '—'}</dd>
          <dt>OCR</dt><dd>{summary.ocr_code ?? 'unreadable'}</dd>
          <dt>reference</dt><dd>{summary.reference_language ?? '—'}</dd>
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
      <div class="panel">
        <h2>Prices</h2>
        <dl>
          <dt>EUR</dt><dd>{report.prices?.eur ?? '—'}</dd>
          <dt>USD</dt><dd>{report.prices?.usd ?? '—'}</dd>
        </dl>
      </div>
      {#if report.photos.length > 1}
        <div class="panel">
          <h2>Photos</h2>
          <ul class="photo-list">
            {#each report.photos as photo}
              <li>
                <img src={`/api/runs/${enc(run)}/results/${enc(group)}/input?thumb=1`} alt="" />
                <span class="muted">{photo.excluded ? 'excluded' : 'used'}</span>
              </li>
            {/each}
          </ul>
        </div>
      {/if}
    </div>

    <details class="raw">
      <summary class="muted">raw result JSON</summary>
      <pre>{JSON.stringify(report, null, 2)}</pre>
    </details>
  </section>
{/if}
