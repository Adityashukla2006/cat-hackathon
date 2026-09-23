import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from '../App'

describe('App shell', () => {
  it('renders the three page links', () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    )
    for (const name of ['Tablet', 'Training', 'Supervisor']) {
      expect(screen.getByRole('link', { name })).toBeInTheDocument()
    }
  })

  it('navigates to the training page', async () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('link', { name: 'Training' }))
    expect(screen.getByRole('heading', { name: 'Training' })).toBeInTheDocument()
  })
})
