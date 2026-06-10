import { useState, useEffect, useRef } from 'react';
import './App.css';

const SPEAKERS = {
  user: { name: 'You', sub: 'Mentor', initial: 'Y' },
  assistant: { name: 'Alex', sub: 'Mentee', initial: 'A' },
};

function renderWhisper(text) {
  const parts = text.split(/(".*?")/g);
  return parts.map((part, i) =>
    part.length >= 2 && part.startsWith('"') && part.endsWith('"')
      ? <em key={i}>{part}</em>
      : <span key={i}>{part}</span>
  );
}

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
  const [whispers, setWhispers] = useState([]);
  const [reflecting, setReflecting] = useState(false);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [voiceOn, setVoiceOn] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const wsRef = useRef(null);
  const replyRef = useRef('');
  const voiceOnRef = useRef(false);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const messagesEndRef = useRef(null);
  const whispersEndRef = useRef(null);

  useEffect(() => { voiceOnRef.current = voiceOn; }, [voiceOn]);

  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/ws');

    ws.onerror = () => { setLoading(false); setReflecting(false); };
    ws.onclose = () => { setLoading(false); setReflecting(false); };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'history') {
        setMessages(data.messages);
        if (data.whispers) setWhispers(data.whispers);
      } else if (data.type === 'token') {
        replyRef.current += data.content;
        setMessages((prev) => {
          const updated = [...prev];
          if (updated.length > 0 && updated[updated.length - 1].role === 'assistant') {
            updated[updated.length - 1].content += data.content;
          }
          return updated;
        });
      } else if (data.type === 'done') {
        setLoading(false);
        setReflecting(true);
        if (voiceOnRef.current) speak(replyRef.current);
        replyRef.current = '';
      } else if (data.type === 'whisper') {
        setReflecting(false);
        setWhispers((prev) => [...prev, data.content]);
      }
    };

    wsRef.current = ws;
    return () => ws.close();
  }, []);

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);
  useEffect(() => { whispersEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [whispers, reflecting]);

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

  const handleSend = () => {
    if (!input.trim()) return;
    sendMessage(input);
    setInput('');
  };

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

  const stopRecording = () => {
    if (mediaRecorderRef.current && recording) {
      mediaRecorderRef.current.stop();
      setRecording(false);
    }
  };

  const transcribeAndSend = async (blob) => {
    setTranscribing(true);
    const form = new FormData();
    form.append('audio', blob, 'audio.webm');
    try {
      const res = await fetch('http://localhost:8000/transcribe', { method: 'POST', body: form });
      const data = await res.json();
      console.log('Transcribe response:', data);
      const text = (data.text || '').trim();
      if (text) sendMessage(text);
      else console.warn('Empty transcription — nothing sent');
    } catch (err) {
      console.error('Transcription request failed:', err);
    } finally {
      setTranscribing(false);
    }
  };

  return (
    <div className="app">
      <div className="conversation-panel">
        <div className="panel-header">
          <span>Practice Conversation</span>
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
            placeholder={transcribing ? 'Transcribing…' : recording ? 'Listening…' : 'Respond as the mentor...'}
            disabled={loading || recording || transcribing}
          />
          <button onClick={handleSend} disabled={loading || recording || transcribing}>Send</button>
        </div>
      </div>

      <div className="whisper-panel">
        <div className="panel-header">✦ Muse</div>
        <div className="whispers">
          {whispers.length === 0 && !reflecting && (
            <div className="whisper-empty">Muse is listening. Private coaching appears here after each exchange.</div>
          )}
          {whispers.map((w, idx) => (
            <div key={idx} className="whisper-card">
              <div className="whisper-label">Read Between the Lines</div>
              <div className="whisper-route">
                <span className="muse-mark">✦</span> Muse → Mentor
                <span className="whisper-private">Private</span>
              </div>
              <div className="whisper-body">{renderWhisper(w)}</div>
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