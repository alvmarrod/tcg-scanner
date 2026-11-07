<script>
  import { onMount } from 'svelte'
  import { getJSON, enc } from './api.js'

  let runs = $state([])
  let error = $state(null)
  let loading = $state(true)

  onMount(async () => {
    try {
      runs = (await getJSON('/api/runs')).runs
    } catch (problem) {
      error = problem.message
    } finally {
      loading = false
    }
  })
</script>

<section class="page">
  <h1>Runs</h1>
  {#if loading}
    <p class="muted">Loading…</p>
  {:else if error}
    <p class="error">{error}</p>
  {:else if runs.length === 0}
    <p class="muted">No runs yet. Run <code>tcg-scanner batch</code>.</p>
  {:else}
    <div class="run-grid">
      {#each runs as run}
        <a class="run-card" href={`#/run/${enc(run.name)}`}>
          <strong>{run.name}</strong>
          <span class="muted">{run.groups} cards · {run.photos} photos</span>
          {#if run.created_at}<span class="muted small">{run.created_at.replace('T', ' ')}</span>{/if}
        </a>
      {/each}
    </div>
  {/if}
</section>
