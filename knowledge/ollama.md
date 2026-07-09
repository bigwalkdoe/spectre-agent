# Ollama Knowledge

- Default endpoint: `http://localhost:11434`
- API: `/api/generate`, `/api/chat`, `/api/embeddings`
- Models stored in `~/.ollama/models/`
- Common models: llama3, mistral, codellama, nomic-embed-text
- Pull model: `ollama pull llama3`
- Run model: `ollama run llama3`
- Custom model: `ollama create mymodel -f Modelfile`
- Keep alive: set `OLLAMA_KEEP_ALIVE` to keep models loaded
