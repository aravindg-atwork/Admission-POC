using System.Collections.Generic;
using System.Threading.Tasks;

namespace AdmissionAssistant.Core.Embeddings
{
    public interface IEmbeddingClient
    {
        Task<float[]> EmbedAsync(string text);
        Task<List<float[]>> EmbedBatchAsync(IEnumerable<string> texts);
    }
}
