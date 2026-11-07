import { enc, getJSON } from './api.js'

export async function startRetry(run, groups) {
  const response = await fetch(`/api/runs/${enc(run)}/retry`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ groups }),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = data.detail
    const message =
      typeof detail === 'string'
        ? detail
        : detail?.message || `${response.status} ${response.statusText}`
    throw new Error(message)
  }
  return data.job_id
}

export async function waitForJob(jobId, onUpdate) {
  while (true) {
    const job = await getJSON(`/api/jobs/${enc(jobId)}`)
    onUpdate(job)
    if (job.state === 'done' || job.state === 'failed') return job
    await new Promise((resolve) => setTimeout(resolve, 700))
  }
}
