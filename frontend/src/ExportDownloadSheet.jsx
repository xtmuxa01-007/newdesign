import React, { useEffect, useState } from 'react';
import { Download, FileDown, Share2 } from 'lucide-react';
import { Modal } from './components';
import { canShareFile, downloadBlob, EXPORT_READY_EVENT, exportSize } from './downloads';

export function ExportDownloadSheet() {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const ready = (event) => {
      const { blob, filename } = event.detail || {};
      if (!(blob instanceof Blob) || typeof filename !== 'string' || !filename) return;
      event.preventDefault();
      setFile(new File([blob], filename, { type: blob.type || 'application/octet-stream' }));
      setError('');
    };
    window.addEventListener(EXPORT_READY_EVENT, ready);
    return () => window.removeEventListener(EXPORT_READY_EVENT, ready);
  }, []);
  if (!file) return null;
  const close = () => setFile(null);
  async function share() {
    if (busy) return;
    const selected = file;
    setBusy(true);
    setError('');
    try {
      // This call starts from a separate tap, after the authenticated fetch finished.
      await navigator.share({ files: [selected], title: 'TIN CRM hisoboti' });
      setFile((current) => (current === selected ? null : current));
    } catch (failure) {
      if (failure.name !== 'AbortError')
        setError('Faylni ulashib bo‘lmadi. «Yuklab olish» tugmasini sinab ko‘ring.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Hisobot tayyor" className="export-download-sheet" onClose={close} busy={busy}>
      <div className="export-file-details">
        <FileDown size={28} aria-hidden="true" />
        <div>
          <strong>{file.name}</strong>
          <small>{exportSize(file.size)}</small>
        </div>
      </div>
      <p>
        {canShareFile(file)
          ? '«Ulashish» orqali faylni iPhone’dagi «Fayllar»ga saqlang yoki kerakli ilovani tanlang.'
          : 'Hisobotni qurilmangizga saqlash uchun «Yuklab olish»ni bosing.'}
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="form-footer">
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => downloadBlob(file, file.name)}
        >
          <Download size={16} /> Yuklab olish
        </button>
        {canShareFile(file) && (
          <button type="button" className="primary" disabled={busy} onClick={share}>
            <Share2 size={16} /> {busy ? 'Ochilmoqda…' : 'Ulashish / Saqlash'}
          </button>
        )}
      </div>
    </Modal>
  );
}
