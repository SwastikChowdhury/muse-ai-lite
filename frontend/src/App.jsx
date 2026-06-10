import { useState, useEffect, useRef } from 'react';
import './App.css';

export default function App() {
  const [messages, setMessages] = useState([]);
  const [whispers, setWhispers] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const wsRef = useRef(null);
  const messagesEndRef = useRef(null);
  const whispersEndRef = useRef(null);

  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/ws');

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === 'history') {
        setMessages(data.messages);
      } else if (data.type === 'token') {
        setMessages((prev) => {
          const updated = [...prev];
          if (updated.length > 0 && updated[updated.length - 1].role === 'assistant') {
            updated[updated.length - 1].content += data.content;
          }
          return updated;
        });
      } else if (data.type === 'done') {
        setLoading(false);
      } else if (data.type === 'whisper') {
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
  }, [whispers]);

  const handleSend = () => {
    if (!input.trim() || loading) return;
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
        <div className="panel-header">Practice Conversation</div>
        <div className="messages">
          {messages.map((msg, idx) => (
            <div key={idx} className={`message ${msg.role}`}>
              <div className="message-content">{msg.content}</div>
            </div>
          ))}
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
          {whispers.length === 0 && (
            <div className="whisper-empty">
              Muse is listening. Private coaching appears here after each exchange.
            </div>
          )}
          {whispers.map((w, idx) => (
            <div key={idx} className="whisper">{w}</div>
          ))}
          <div ref={whispersEndRef} />
        </div>
      </div>
    </div>
  );
}