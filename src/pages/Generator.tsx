import { useState } from 'react';
import Editor from '@monaco-editor/react';

export default function Generator() {
  const [prompt, setPrompt] = useState('');
  const [code, setCode] = useState('');
  const [loading, setLoading] = useState(false);

  const handleGenerate = async () => {
    setLoading(true);
    try {
      // TODO: Implement AI generation logic
      const response = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      });
      const data = await response.json();
      setCode(data.code);
    } catch (error) {
      console.error('Generation failed:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="grid grid-cols-2 gap-8">
        <div>
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700">
              Describe what you want to create
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
              rows={4}
            />
          </div>
          <button
            onClick={handleGenerate}
            disabled={loading || !prompt}
            className="w-full px-4 py-2 rounded-md text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50"
          >
            {loading ? 'Generating...' : 'Generate Code'}
          </button>
        </div>
        <div className="h-[600px] border rounded-lg overflow-hidden">
          <Editor
            height="100%"
            defaultLanguage="javascript"
            value={code}
            theme="vs-dark"
            options={{
              minimap: { enabled: false },
              fontSize: 14,
            }}
          />
        </div>
      </div>
    </div>
  );
}