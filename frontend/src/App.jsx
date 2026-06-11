/**
 * App.jsx — the entire single-page UI for the Muse practice tool.
 *
 * Two-panel layout: a live chat with the AI "mentee" (left) and a private
 * coaching "whisper" feed from Muse (right). This component is the frontend
 * counterpart to backend/main.py's /ws endpoint and speaks its JSON protocol
 * directly:
 *   incoming  - {type:"history"|"token"|"done"|"whisper", ...}
 *   outgoing  - raw text (the mentor's message)
 *
 * Responsibilities held here: WebSocket lifecycle, streaming-token assembly
 * into the chat, optional voice input (mic -> /transcribe) and output
 * (browser speech synthesis), and autoscroll. There is no router or global
 * store — state is local because the app is intentionally one screen.
 */
import { useState, useEffect, useRef } from 'react';
import './App.css';

// Display metadata per message role. `assistant` is the AI mentee ("Alex");
// `user` is the human mentor. Used to label/avatar each bubble consistently.
const SPEAKERS = {
  user: { name: 'You', sub: 'Mentor', initial: 'Y' },
  assistant: { name: 'Alex', sub: 'Mentee', initial: 'A' },
};

/**
 * Render a whisper string with any "quoted" spans italicized.
 *
 * The coach often suggests example phrasing in quotes; we emphasize those so
 * the mentor can spot the suggested wording at a glance. Splitting on a
 * capturing regex keeps the quotes as their own array entries, and the React
 * `key` is the index because the parts are positional and never reordered.
 */
function renderWhisper(text) {
  const parts = text.split(/(".*?")/g);
  return parts.map((part, i) =>
    part.length >= 2 && part.startsWith('"') && part.endsWith('"')
      ? <em key={i}>{part}</em>
      : <span key={i}>{part}</span>
  );
}

/**
 * Speak text aloud via the browser's SpeechSynthesis API (used when voice
 * output is toggled on). Cancels any in-flight utterance first so replies
 * don't queue up and overlap. No-ops when text is empty or the API is
 * unavailable. Pitch is nudged slightly up to suit the mentee persona.
 */
function speak(text) {
  if (!text || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.rate = 1.0;
  utter.pitch = 1.05;
  window.speechSynthesis.speak(utter);
}

export default function App() {
  const [messages, setMessages] = useState([]);
  const [whispers, setWhispers] = useState([]);   // { label, content }
  // True between a mentee reply finishing and its whisper arriving — drives the
  // "Muse is reflecting…" indicator in the right panel.
  const [reflecting, setReflecting] = useState(false);
  const [input, setInput] = useState('');
  // True while a turn is in flight; disables the composer so the user can't
  // send a second message mid-stream.
  const [loading, setLoading] = useState(false);
  const [voiceOn, setVoiceOn] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const wsRef = useRef(null);
  // Accumulates the streamed mentee reply across many token frames so the whole
  // utterance can be spoken once on "done". A ref (not state) because it changes
  // on every token and must not trigger re-renders.
  const replyRef = useRef('');
  // Mirror of `voiceOn` readable inside the ws.onmessage closure. The effect
  // that sets up the socket runs once, so it would otherwise capture the initial
  // voiceOn value forever; this ref gives the handler the current setting.
  const voiceOnRef = useRef(false);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const messagesEndRef = useRef(null);
  const whispersEndRef = useRef(null);

  // Keep the voice-on ref in sync with state for the long-lived ws handler.
  useEffect(() => { voiceOnRef.current = voiceOn; }, [voiceOn]);

  // Open the chat socket once on mount and route inbound frames by type. Runs
  // with an empty dep array so a single connection lives for the component's
  // lifetime; the cleanup closes it on unmount.
  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/ws');
    // On any connection failure/close, clear the in-flight indicators so the UI
    // doesn't hang on a spinner.
    ws.onerror = () => { setLoading(false); setReflecting(false); };
    ws.onclose = () => { setLoading(false); setReflecting(false); };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'history') {
        // Rehydrate from server on connect. Persisted whispers arrive as plain
        // strings (the label isn't stored), so default them to "Insight".
        setMessages(data.messages);
        if (data.whispers) {
          setWhispers(data.whispers.map((c) => ({ label: 'Insight', content: c })));
        }
      } else if (data.type === 'token') {
        // Append each streamed chunk to both the spoken-text buffer and the last
        // (assistant) bubble, which sendMessage pre-created as an empty
        // placeholder — so tokens render in place as they arrive.
        replyRef.current += data.content;
        setMessages((prev) => {
          const updated = [...prev];
          if (updated.length > 0 && updated[updated.length - 1].role === 'assistant') {
            updated[updated.length - 1].content += data.content;
          }
          return updated;
        });
      } else if (data.type === 'done') {
        // Mentee reply complete: stop the composer spinner, switch to the
        // "reflecting" state while the whisper is computed, speak the full reply
        // if voice is on, then reset the buffer for the next turn.
        setLoading(false);
        setReflecting(true);
        if (voiceOnRef.current) speak(replyRef.current);
        replyRef.current = '';
      } else if (data.type === 'whisper') {
        setReflecting(false);
        setWhispers((prev) => [...prev, { label: data.label || 'Insight', content: data.content }]);
      }
    };

    wsRef.current = ws;
    return () => ws.close();
  }, []);

  // Autoscroll each panel to its newest item. Whisper scroll also fires on
  // `reflecting` so the "reflecting…" indicator stays in view.
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);
  useEffect(() => { whispersEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [whispers, reflecting]);

  /**
   * Send a mentor message over the socket and optimistically render it.
   *
   * Guards against empty input and double-sends while loading. Pushes the
   * user's bubble plus an empty assistant bubble that the streaming `token`
   * handler will fill in. Shared by both typed and voice-transcribed input.
   */
  const sendMessage = (text) => {
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    setReflecting(false);
    replyRef.current = '';
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: trimmed },
      { role: 'assistant', content: '' },
    ]);
    setLoading(true);
    wsRef.current.send(trimmed);
  };

  /** Send the current text input and clear the field (the typed-message path). */
  const handleSend = () => {
    if (!input.trim()) return;
    sendMessage(input);
    setInput('');
  };

  /**
   * Begin capturing mic audio for voice input.
   *
   * Buffers chunks via MediaRecorder; the actual upload happens in `onstop`
   * (wired here) so recording and transcription are decoupled — the user
   * controls when capture ends. On stop we release the mic tracks (otherwise
   * the browser keeps the "recording" indicator lit) and hand the assembled
   * WebM blob to transcribeAndSend. A denied/missing mic surfaces an alert.
   */
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      audioChunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size > 0) audioChunksRef.current.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        await transcribeAndSend(blob);
      };
      mr.start();
      mediaRecorderRef.current = mr;
      setRecording(true);
    } catch (err) {
      console.error('Mic error:', err);
      alert('Could not access the microphone.');
    }
  };

  /** Stop the active recording, which triggers the recorder's onstop -> upload. */
  const stopRecording = () => {
    if (mediaRecorderRef.current && recording) {
      mediaRecorderRef.current.stop();
      setRecording(false);
    }
  };

  /**
   * Upload recorded audio to the backend /transcribe endpoint and, if it yields
   * text, feed that text into the normal chat flow via sendMessage.
   *
   * `transcribing` gates the UI (composer disabled, placeholder updated) for the
   * round-trip. Failures are logged but non-fatal — the user can simply retry or
   * type instead. Always clears the transcribing flag in `finally`.
   */
  const transcribeAndSend = async (blob) => {
    setTranscribing(true);
    const form = new FormData();
    form.append('audio', blob, 'audio.webm');
    try {
      const res = await fetch('http://localhost:8000/transcribe', { method: 'POST', body: form });
      const data = await res.json();
      const text = (data.text || '').trim();
      if (text) sendMessage(text);
    } catch (err) {
      console.error('Transcription request failed:', err);
    } finally {
      setTranscribing(false);
    }
  };

  return (
    <div className="app">
      <div className="conversation-panel">
        <div className="chat-header">
          <div className="contact">
            <div className="avatar lg">A</div>
            <div className="contact-meta">
              <div className="contact-name">Alex</div>
              <div className="contact-role">Mentee · practice partner</div>
            </div>
          </div>
          <button
            className="voice-toggle"
            onClick={() => { if (voiceOn) window.speechSynthesis.cancel(); setVoiceOn((v) => !v); }}
          >
            {voiceOn ? '🔊 Voice on' : '🔈 Voice off'}
          </button>
        </div>

        <div className="messages">
          {messages.map((msg, idx) => {
            const sp = SPEAKERS[msg.role] || SPEAKERS.assistant;
            return (
              <div key={idx} className={`message ${msg.role}`}>
                <div className="avatar">{sp.initial}</div>
                <div className="bubble-col">
                  <div className="speaker-name">{sp.name}<span className="speaker-sub"> · {sp.sub}</span></div>
                  <div className="message-content">{msg.content}</div>
                </div>
              </div>
            );
          })}
          <div ref={messagesEndRef} />
        </div>

        <div className="input-area">
          <button
            className={`mic-btn ${recording ? 'recording' : ''}`}
            onClick={recording ? stopRecording : startRecording}
            disabled={loading || transcribing}
            title="Speak as the mentor"
          >
            {recording ? '■' : '🎤'}
          </button>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            placeholder={transcribing ? 'Transcribing…' : recording ? 'Listening…' : 'Respond as the mentor…'}
            disabled={loading || recording || transcribing}
          />
          <button onClick={handleSend} disabled={loading || recording || transcribing}>Send</button>
        </div>
      </div>

      <div className="whisper-panel">
        <div className="muse-header">
          <div className="muse-title">✦ Muse</div>
          <div className="muse-sub">Private to you · the mentee can't see this</div>
        </div>
        <div className="whispers">
          {whispers.length === 0 && !reflecting && (
            <div className="whisper-empty">Muse is listening. Coaching appears here after each exchange.</div>
          )}
          {whispers.map((w, idx) => (
            <div key={idx} className="whisper-card">
              <div className="whisper-tag">{w.label}</div>
              <div className="whisper-body">{renderWhisper(w.content)}</div>
            </div>
          ))}
          {reflecting && (
            <div className="reflecting"><span className="muse-mark">✦</span> Muse is reflecting<span>…</span></div>
          )}
          <div ref={whispersEndRef} />
        </div>
      </div>
    </div>
  );
}