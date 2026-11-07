<script>
  import { onMount } from 'svelte'
  import Runs from './lib/Runs.svelte'
  import Run from './lib/Run.svelte'
  import Result from './lib/Result.svelte'

  function parseRoute() {
    const parts = (location.hash.replace(/^#/, '') || '/')
      .split('/')
      .filter(Boolean)
      .map(decodeURIComponent)
    if (parts[0] === 'run' && parts[1]) {
      if (parts[2] === 'result' && parts[3]) {
        return { view: 'result', run: parts[1], group: parts[3] }
      }
      return { view: 'run', run: parts[1] }
    }
    return { view: 'runs' }
  }

  let route = $state(parseRoute())
  let theme = $state('dark')

  onMount(() => {
    theme = localStorage.getItem('theme') || 'dark'
    document.documentElement.dataset.theme = theme
    const update = () => { route = parseRoute() }
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  })

  function toggleTheme() {
    theme = theme === 'dark' ? 'light' : 'dark'
    document.documentElement.dataset.theme = theme
    localStorage.setItem('theme', theme)
  }
</script>

<header class="topbar">
  <a class="brand" href="#/">tcg-scanner <span class="muted">results</span></a>
  <button class="ghost" onclick={toggleTheme}>{theme === 'dark' ? '☀ light' : '☾ dark'}</button>
</header>

<main>
  {#if route.view === 'runs'}
    <Runs />
  {:else if route.view === 'run'}
    {#key route.run}<Run name={route.run} />{/key}
  {:else}
    {#key `${route.run}/${route.group}`}<Result run={route.run} group={route.group} />{/key}
  {/if}
</main>
