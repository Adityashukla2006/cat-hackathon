import config from '../../vercel.json'

describe('vercel config', () => {
  it('builds the vite app into dist', () => {
    expect(config.framework).toBe('vite')
    expect(config.buildCommand).toBe('npm run build')
    expect(config.outputDirectory).toBe('dist')
  })

  it('rewrites client routes to index.html so deep links load', () => {
    expect(config.rewrites).toContainEqual({ source: '/(.*)', destination: '/index.html' })
  })
})
