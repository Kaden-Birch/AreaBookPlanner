// Shared note helpers: @-mention autocomplete and the photo detail modal.
import { clinics, attachments } from './api.js';
import { esc, attr, fmtDateTime, renderNoteBody, openModal, toast, confirmDialog, getRepName } from './ui.js';

export function contactName(c) {
  return `${c.first_name || ''} ${c.last_name || ''}`.trim() || 'Contact';
}

// Attach an @-mention picker to a textarea. `contacts` is the list of mentionable
// contacts (already limited to the clinic + its group by the backend/get_clinic).
export function attachMentionAutocomplete(textarea, contacts) {
  if (!textarea || !contacts || !contacts.length) return;
  const parent = textarea.parentElement;
  if (getComputedStyle(parent).position === 'static') parent.style.position = 'relative';
  const menu = document.createElement('div');
  menu.className = 'mention-menu hidden';
  parent.appendChild(menu);
  let matches = [];
  let active = 0;
  let anchor = 0; // index of the '@' being completed

  const hide = () => { menu.classList.add('hidden'); matches = []; };
  const place = () => {
    menu.style.top = (textarea.offsetTop + textarea.offsetHeight) + 'px';
    menu.style.left = textarea.offsetLeft + 'px';
    menu.style.minWidth = Math.min(280, textarea.offsetWidth) + 'px';
  };
  const draw = () => {
    menu.innerHTML = matches.map((c, i) => `<button type="button" data-i="${i}" class="${i === active ? 'active' : ''}">@${esc(contactName(c))}${c.role_label ? ` <span class="muted">${esc(c.role_label)}</span>` : ''}</button>`).join('');
    menu.querySelectorAll('button').forEach(b => b.onmousedown = (e) => { e.preventDefault(); choose(Number(b.dataset.i)); });
  };
  const refresh = () => {
    const caret = textarea.selectionStart;
    const before = textarea.value.slice(0, caret);
    const m = before.match(/@([^\s@]{0,40})$/);
    if (!m) return hide();
    anchor = caret - m[0].length;
    const q = m[1].toLowerCase();
    matches = contacts.filter(c => contactName(c).toLowerCase().includes(q)).slice(0, 6);
    if (!matches.length) return hide();
    active = 0;
    place(); draw();
    menu.classList.remove('hidden');
  };
  const choose = (i) => {
    const c = matches[i];
    if (!c) return;
    const caret = textarea.selectionStart;
    const token = `@[${contactName(c)}](c:${c.id}) `;
    textarea.value = textarea.value.slice(0, anchor) + token + textarea.value.slice(caret);
    const pos = anchor + token.length;
    textarea.setSelectionRange(pos, pos);
    textarea.focus();
    hide();
  };

  textarea.addEventListener('input', refresh);
  textarea.addEventListener('keydown', (e) => {
    if (menu.classList.contains('hidden')) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); active = (active + 1) % matches.length; draw(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); active = (active - 1 + matches.length) % matches.length; draw(); }
    else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); choose(active); }
    else if (e.key === 'Escape') { hide(); }
  });
  textarea.addEventListener('blur', () => setTimeout(hide, 150));
}

// Wire mention chips inside a container so clicking one opens that contact.
export function wireMentionChips(container, onContact) {
  container.querySelectorAll('.mention[data-contact]').forEach(el => {
    el.onclick = (e) => { e.preventDefault(); onContact(Number(el.dataset.contact)); };
  });
}

// Photo detail: the image plus notes attached directly to it, with an add-note box.
export async function openPhotoModal({ clinic, photo, onSaved, onContact, onOrigin }) {
  const o = photo.origin;
  const originBanner = o && (o.type === 'appointment' || o.type === 'task')
    ? `<div class="photo-origin">From ${o.type === 'appointment' ? '📍 appointment' : '☑ task'}: <a href="#" id="photo-origin-link">${esc(o.label || o.type)}</a> →</div>`
    : (o && o.type === 'note' ? '<div class="photo-origin muted">Uploaded with a note.</div>' : '');
  const modal = openModal({
    title: photo.caption || photo.filename || 'Photo',
    size: 'modal-lg',
    body: `
      <div class="photo-detail">
        <img src="${attachments.fileUrl(photo.id)}" alt="${attr(photo.caption || photo.filename)}">
        ${originBanner}
        <div class="photo-notes" id="photo-notes"><p class="muted">Loading notes…</p></div>
        <form id="photo-note-form" class="note-compose">
          <textarea name="body" rows="2" placeholder="Add a note about this photo… (type @ to mention a contact)"></textarea>
          <div class="right mt"><button class="btn btn-primary btn-sm" type="submit">Add note</button></div>
        </form>
      </div>`,
    footer: `<button class="btn btn-danger left" data-act="delete">Delete photo</button><button class="btn" data-act="cancel">Close</button>`,
  });
  const notesEl = modal.body.querySelector('#photo-notes');
  const form = modal.body.querySelector('#photo-note-form');
  attachMentionAutocomplete(form.elements.body, clinic.contacts || []);

  const loadNotes = async () => {
    const notes = await clinics.photoNotes(clinic.id, photo.id).catch(() => []);
    notesEl.innerHTML = notes.length ? notes.map(n => `
      <div class="photo-note" data-id="${n.id}">
        <div class="body">${renderNoteBody(n.body)}</div>
        <div class="muted small">${esc(fmtDateTime(n.created_at))}${n.author ? ` · ${esc(n.author)}` : ''}
          <button class="btn btn-link btn-sm" data-del="${n.id}">delete</button></div>
      </div>`).join('') : '<p class="muted">No notes on this photo yet.</p>';
    if (onContact) wireMentionChips(notesEl, onContact);
    notesEl.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
      await clinics.removeNote(clinic.id, Number(b.dataset.del)); loadNotes();
    });
  };
  loadNotes();

  form.onsubmit = async (e) => {
    e.preventDefault();
    const body = form.elements.body.value.trim();
    if (!body) return;
    try {
      await clinics.addNote(clinic.id, body, 'note', getRepName() || null, { attachment_id: photo.id });
      form.elements.body.value = '';
      loadNotes();
      onSaved && onSaved();
    } catch (err) { toast(err.message, 'error'); }
  };
  const originLink = modal.body.querySelector('#photo-origin-link');
  if (originLink && onOrigin) originLink.onclick = (e) => { e.preventDefault(); modal.close(); onOrigin(o); };
  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  modal.root.querySelector('[data-act=delete]').onclick = async () => {
    if (!(await confirmDialog('Delete this photo? Any notes on it are removed too.'))) return;
    await attachments.remove(photo.id);
    toast('Photo deleted');
    modal.close();
    onSaved && onSaved();
  };
}
