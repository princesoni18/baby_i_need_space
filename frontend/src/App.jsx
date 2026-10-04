import { useEffect, useState, useCallback } from 'react'
import './App.css'

const API = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000') + '/api'

async function call(path, method = 'GET', body) {
  const res = await fetch(API + path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`)
  return data
}

export default function App() {
  const [contacts, setContacts] = useState([])
  const [scheduled, setScheduled] = useState([])
  const [selected, setSelected] = useState(null)
  const [messages, setMessages] = useState([])
  const [note, setNote] = useState('')
  const [newContact, setNewContact] = useState({ name: '', phone_number: '' })
  const [sched, setSched] = useState({ contact_id: '', content: '', when: '' })
  const [myName, setMyName] = useState('')
  const [drafts, setDrafts] = useState([])
  const [edits, setEdits] = useState({})
  const [style, setStyle] = useState(null)

  const flash = (m) => { setNote(m); setTimeout(() => setNote(''), 5000) }
  const guard = (fn) => async (...a) => { try { await fn(...a) } catch (e) { flash('Error: ' + e.message) } }

  const load = useCallback(async () => {
    try {
      setContacts(await call('/contacts'))
      setScheduled(await call('/scheduled'))
      setDrafts(await call('/drafts'))
      setStyle(await call('/style'))
    } catch (e) { flash('Backend not reachable: ' + e.message) }
  }, [])

  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t) }, [load])

  useEffect(() => {
    if (!selected) { setMessages([]); return }
    call(`/contacts/${selected.id}/messages`).then(setMessages).catch(() => {})
  }, [selected, contacts])

  const addContact = guard(async (e) => {
    e.preventDefault()
    await call('/contacts', 'POST', newContact)
    setNewContact({ name: '', phone_number: '' })
    load()
  })

  const toggleAI = guard(async (c) => {
    await call(`/contacts/${c.id}`, 'PATCH', { auto_reply_enabled: !c.auto_reply_enabled })
    load()
  })

  const schedule = guard(async (e) => {
    e.preventDefault()
    await call('/scheduled', 'POST', {
      contact_id: Number(sched.contact_id),
      content: sched.content,
      scheduled_at: new Date(sched.when).toISOString(),
    })
    setSched({ ...sched, content: '' })
    flash('Message scheduled')
    load()
  })

  const sendDraft = guard(async (d) => {
    await call(`/drafts/${d.id}/send`, 'POST', { text: edits[d.id] ?? d.draft })
    flash('Sent')
    load()
  })
  const dismissDraft = guard(async (d) => { await call(`/drafts/${d.id}`, 'DELETE'); load() })
  const rebuildStyle = guard(async () => { await call('/style/rebuild', 'POST'); flash('Style profile rebuilt'); load() })

  const cancel = guard(async (id) => { await call(`/scheduled/${id}`, 'DELETE'); load() })

  const upload = guard(async (file) => {
    if (!file || !selected) return
    if (!myName.trim()) return flash('Enter your name exactly as it appears in the export first')
    const text = await file.text()
    const r = await call(`/contacts/${selected.id}/history`, 'POST', { text, my_name: myName.trim() })
    flash(`Imported ${r.imported} messages (${r.indexed} indexed for AI memory)`)
    load()
  })

  return (
    <div className="app">
      <h1>WhatsApp AI Companion</h1>
      {note && <div className="note">{note}</div>}

      <section>
        <h2>Draft replies to review {drafts.length > 0 && `(${drafts.length})`}</h2>
        <p className="muted">For contacts with AI auto-reply Off, the AI writes a draft instead of sending. Edit it if you like, then send.</p>
        {drafts.map((d) => (
          <div key={d.id} className="draft">
            <div className="muted">{d.contact_name} said:</div>
            <div className="bubble incoming">{d.incoming}</div>
            <textarea rows="2" value={edits[d.id] ?? d.draft} onChange={(e) => setEdits({ ...edits, [d.id]: e.target.value })} />
            <div className="row">
              <button onClick={() => sendDraft(d)}>Send</button>
              <button className="ghost" onClick={() => dismissDraft(d)}>Dismiss</button>
            </div>
          </div>
        ))}
        {!drafts.length && <p className="muted">No drafts waiting.</p>}
      </section>

      <section>
        <h2>How the AI thinks you text</h2>
        <p style={{ whiteSpace: 'pre-wrap' }}>{style?.summary || 'Not learned yet. Upload an exported chat first.'}</p>
        {style?.summary && <p className="muted">Learned from {style.sample_size} of your messages.</p>}
        <button className="ghost" onClick={rebuildStyle}>Re-learn my style</button>
      </section>

      <section>
        <h2>Contacts</h2>
        <form className="row" onSubmit={addContact}>
          <input placeholder="Name" value={newContact.name} onChange={(e) => setNewContact({ ...newContact, name: e.target.value })} />
          <input placeholder="Phone with country code, e.g. 15551234567" required value={newContact.phone_number} onChange={(e) => setNewContact({ ...newContact, phone_number: e.target.value })} />
          <button>Add</button>
        </form>
        <table>
          <thead><tr><th>Name</th><th>Number</th><th>Messages</th><th>AI auto-reply</th><th></th></tr></thead>
          <tbody>
            {contacts.map((c) => (
              <tr key={c.id} className={selected?.id === c.id ? 'sel' : ''}>
                <td>{c.name}</td>
                <td>{c.phone_number}</td>
                <td>{c.message_count}</td>
                <td>
                  <label className="switch">
                    <input type="checkbox" checked={c.auto_reply_enabled} onChange={() => toggleAI(c)} />
                    {c.auto_reply_enabled ? 'On' : 'Off'}
                  </label>
                </td>
                <td><button className="ghost" onClick={() => setSelected(c)}>Open</button></td>
              </tr>
            ))}
            {!contacts.length && <tr><td colSpan="5" className="muted">No contacts yet. Anyone who messages your number is added automatically.</td></tr>}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Schedule a message</h2>
        <form className="col" onSubmit={schedule}>
          <div className="row">
            <select required value={sched.contact_id} onChange={(e) => setSched({ ...sched, contact_id: e.target.value })}>
              <option value="">Choose contact…</option>
              {contacts.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.phone_number})</option>)}
            </select>
            <input type="datetime-local" required value={sched.when} onChange={(e) => setSched({ ...sched, when: e.target.value })} />
          </div>
          <textarea required rows="3" placeholder="Message text" value={sched.content} onChange={(e) => setSched({ ...sched, content: e.target.value })} />
          <button>Schedule</button>
        </form>
        <table>
          <thead><tr><th>To</th><th>When</th><th>Message</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {scheduled.map((s) => (
              <tr key={s.id}>
                <td>{s.contact_name}</td>
                <td>{new Date(s.scheduled_at).toLocaleString()}</td>
                <td>{s.content}</td>
                <td><span className={`tag ${s.status}`}>{s.status}</span></td>
                <td>{s.status === 'pending' && <button className="ghost" onClick={() => cancel(s.id)}>Cancel</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {selected && (
        <section>
          <h2>{selected.name}: chat history</h2>
          <div className="row">
            <input placeholder="Your name in the export" value={myName} onChange={(e) => setMyName(e.target.value)} />
            <input type="file" accept=".txt" onChange={(e) => upload(e.target.files[0])} />
          </div>
          <p className="muted">In WhatsApp: open the chat, More, Export chat, Without media. Upload the .txt here. Lines from you become your style examples for the AI.</p>
          <div className="chat">
            {messages.map((m) => (
              <div key={m.id} className={`bubble ${m.direction}`}>{m.content}</div>
            ))}
            {!messages.length && <p className="muted">No messages yet.</p>}
          </div>
        </section>
      )}
    </div>
  )
}
