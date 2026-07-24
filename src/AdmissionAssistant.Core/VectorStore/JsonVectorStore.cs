using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json;
using AdmissionAssistant.Core.Chunking;

namespace AdmissionAssistant.Core.VectorStore
{
    // In-app vector store: embeddings for a single prospectus fit comfortably in memory
    // at POC scale, so this avoids standing up a dedicated vector database.
    public class JsonVectorStore : IVectorStore
    {
        private readonly string _filePath;
        private List<Entry> _entries = new List<Entry>();

        public JsonVectorStore(string filePath)
        {
            _filePath = filePath;
        }

        public void Add(Chunk chunk, float[] embedding)
        {
            _entries.Add(new Entry { Chunk = chunk, Embedding = embedding });
        }

        public void Clear()
        {
            _entries = new List<Entry>();
        }

        public void Save()
        {
            var dir = Path.GetDirectoryName(_filePath);
            if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                Directory.CreateDirectory(dir);

            File.WriteAllText(_filePath, JsonConvert.SerializeObject(_entries));
        }

        public void Load()
        {
            _entries = File.Exists(_filePath)
                ? JsonConvert.DeserializeObject<List<Entry>>(File.ReadAllText(_filePath))
                : new List<Entry>();
        }

        public List<ScoredChunk> Search(float[] queryEmbedding, int topK)
        {
            return _entries
                .Select(e => new ScoredChunk { Chunk = e.Chunk, Score = CosineSimilarity.Compute(queryEmbedding, e.Embedding) })
                .OrderByDescending(s => s.Score)
                .Take(topK)
                .ToList();
        }

        private class Entry
        {
            public Chunk Chunk { get; set; }
            public float[] Embedding { get; set; }
        }
    }
}
