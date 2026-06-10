import { useState, useEffect, useRef } from 'react';
import './App.css';

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const wsRef = useRef(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/ws');
  
    ws.onmessage = (event) => {
      setMessages((prev) => {
        const updated = [...prev];
        if (updated.length > 0 && updated[updated.length - 1].role === 'assistant') {
          updated[updated.length - 1].content += event.data;
        }
        return updated;
      });
    };
  
    wsRef.current = ws;
  
    return () => {
      ws.close();
    };
  }, []);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = () => {
    if (!input.trim() || loading) return;

    // Add user message
    setMessages((prev) => [...prev, { role: 'user', content: input }]);
    // Add empty assistant message placeholder
    setMessages((prev) => [...prev, { role: 'assistant', content: '' }]);
    
    setLoading(true);
    wsRef.current.send(input);
    setInput('');

    // Stop loading once we get the first chunk (optional; you could wait for a real "done" signal)
    setTimeout(() => setLoading(false), 100);
  };

  return (
    <div className="chat-container">
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
          placeholder="Type a message..."
          disabled={loading}
        />
        <button onClick={handleSend} disabled={loading}>
          Send
        </button>
      </div>
    </div>
  );
}