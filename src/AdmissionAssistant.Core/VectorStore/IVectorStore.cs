using System.Collections.Generic;
using AdmissionAssistant.Core.Chunking;

namespace AdmissionAssistant.Core.VectorStore
{
    public class ScoredChunk
    {
        public Chunk Chunk { get; set; }
        public float Score { get; set; }
    }

    public interface IVectorStore
    {
        void Add(Chunk chunk, float[] embedding);
        void Clear();
        void Save();
        void Load();
        List<ScoredChunk> Search(float[] queryEmbedding, int topK);
    }
}
