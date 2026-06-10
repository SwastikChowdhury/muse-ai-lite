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
  const wsRef = useRef(null);
  const replyRef = useRef('');
  const voiceOnRef = useRef(false);
  const messagesEndRef = useRef(null);
  const whispersEndRef = useRef(null);

  // keep a ref in sync so the WebSocket handler (created once) reads the latest toggle value
  useEffect(() => { voiceOnRef.current = voiceOn; }, [voiceOn]);

  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/ws');

    ws.onerror = () => {
      setLoading(false);
      setReflecting(false);
    };

    ws.onclose = () => {
      setLoading(false);
      setReflecting(false);
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === 'history') {
        setMessages(data.messages);
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

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    whispersEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [whispers, reflecting]);

  const handleSend = () => {
    if (!input.trim() || loading) return;
    setReflecting(false);
    replyRef.current = '';
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: input },
      { role: 'assistant', content: '' },
    ]);
    setLoading(true);
    wsRef.current.send(input);
    setInput('');
  };

  return (
    <div className="app">
      <div className="conversation-panel">
        <div className="panel-header">
          <span>Practice Conversation</span>
          <button
            className="voice-toggle"
            onClick={() => {
              if (voiceOn) window.speechSynthesis.cancel();
              setVoiceOn((v) => !v);
            }}
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
                  <div className="speaker-name">
                    {sp.name}<span className="speaker-sub"> · {sp.sub}</span>
                  </div>
                  <div className="message-content">{msg.content}</div>
                </div>
              </div>
            );
          })}
          <div ref={messagesEndRef} />
        </div>
        <div className="input-area">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            placeholder="Respond as the mentor..."
            disabled={loading}
          />
          <button onClick={handleSend} disabled={loading}>Send</button>
        </div>
      </div>

      <div className="whisper-panel">
        <div className="panel-header">✦ Muse</div>
        <div className="whispers">
          {whispers.length === 0 && !reflecting && (
            <div className="whisper-empty">
              Muse is listening. Private coaching appears here after each exchange.
            </div>
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
            <div className="reflecting">
              <span className="muse-mark">✦</span> Muse is reflecting<span>…</span>
            </div>
          )}
          <div ref={whispersEndRef} />
        </div>
      </div>
    </div>
  );
}