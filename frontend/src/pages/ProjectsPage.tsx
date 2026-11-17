import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { Badge, Card, Empty, ErrorAlert, Spinner } from '../components/ui'
import { useAction, useLoad } from '../hooks'
import { projectStateLabel, stateTone } from '../labels'

export default function ProjectsPage() {
  const { workshop } = useAuth()
  const wid = workshop!.workshop_id
  const isOwner = workshop!.role === 'OWNER'
  const projects = useLoad(() => api.projects(wid), [wid])

  return (
    <>
      <div className="page-head">
        <h1>Projekty</h1>
      </div>

      <Card>
        <ErrorAlert error={projects.error} />
        {projects.loading && !projects.data ? (
          <Spinner />
        ) : projects.data?.length === 0 ? (
          <Empty>Brak projektów.{isOwner && ' Utwórz pierwszy projekt poniżej.'}</Empty>
        ) : (
          projects.data && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Nazwa</th>
                    <th>Stan</th>
                    <th className="num">Elementy</th>
                    <th className="num">Rzaz</th>
                    <th className="num">Min. resztka</th>
                  </tr>
                </thead>
                <tbody>
                  {projects.data.map((p) => (
                    <tr key={p.id} data-testid={`project-row-${p.id}`}>
                      <td>
                        <Link to={`/projects/${p.id}`} className="strong-link">
                          {p.name}
                        </Link>
                      </td>
                      <td>
                        <Badge tone={stateTone[p.state]}>{projectStateLabel[p.state]}</Badge>
                      </td>
                      <td className="num">
                        {p.piece_count} <span className="muted small">({p.demand_lines} poz.)</span>
                      </td>
                      <td className="num">{p.kerf_mm} mm</td>
                      <td className="num">{p.min_remnant_mm} mm</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </Card>

      {isOwner && <CreateProjectForm wid={wid} />}
    </>
  )
}

function CreateProjectForm({ wid }: { wid: number }) {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [kerf, setKerf] = useState('3')
  const [minRemnant, setMinRemnant] = useState('300')
  const action = useAction()

  function submit(e: FormEvent) {
    e.preventDefault()
    action.run(async () => {
      const project = await api.createProject(wid, {
        name,
        kerf_mm: Number(kerf),
        min_remnant_mm: Number(minRemnant),
      })
      navigate(`/projects/${project.id}`)
    })
  }

  return (
    <Card title="Nowy projekt">
      <form onSubmit={submit} className="form-row">
        <label className="grow">
          Nazwa
          <input required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} placeholder="np. Półka do garażu" />
        </label>
        <label>
          Rzaz (mm)
          <input type="number" min={0} max={50} required value={kerf} onChange={(e) => setKerf(e.target.value)} />
        </label>
        <label>
          Min. resztka (mm)
          <input type="number" min={0} max={100000} required value={minRemnant} onChange={(e) => setMinRemnant(e.target.value)} />
        </label>
        <button type="submit" className="btn btn-primary" disabled={action.pending}>
          {action.pending ? 'Tworzenie…' : 'Utwórz projekt'}
        </button>
      </form>
      <ErrorAlert error={action.error} onClose={action.clearError} />
    </Card>
  )
}
